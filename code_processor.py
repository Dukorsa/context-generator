# code_processor.py
import os
import re
from fnmatch import fnmatch
import ast
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
from typing import Set, Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
from collections import defaultdict, Counter # Counter para estatísticas de arquivo

# Tentativa de importação de dependências opcionais
try:
    import pyjsparser
    PYJSPARSER_AVAILABLE = True
except ImportError:
    PYJSPARSER_AVAILABLE = False

try:
    from clang import cindex
    try:
        cindex.Index.create()
        LIBCLANG_AVAILABLE = True
    except Exception:
        LIBCLANG_AVAILABLE = False
except ImportError:
    LIBCLANG_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BEAUTIFULSOUP_AVAILABLE = True
except ImportError:
    BEAUTIFULSOUP_AVAILABLE = False

from config import COMMENT_PATTERNS, IGNORED_ITEMS, SUPPORTED_LANGUAGES, ALL_EFFECTIVELY_SUPPORTED_EXTENSIONS

@dataclass
class FileInfo: # Inalterada
    path: str; content: str; original_content: str; original_name: str
    ext: str; size: int; last_modified: float
    direct_dependencies: Set[str] = field(default_factory=set)
    transitive_dependencies: Set[str] = field(default_factory=set)
    dependency_analysis_status: str = "pending"
    dependency_analysis_error: Optional[str] = None

class DependencyCache: # Inalterada
    def __init__(self): self._cache: Dict[str, Set[str]] = {}; self._lock = threading.Lock()
    def get(self, fp: str) -> Optional[Set[str]]:
        with self._lock: return self._cache.get(fp)
    def set(self, fp: str, deps: Set[str]):
        with self._lock: self._cache[fp] = deps.copy()
    def clear(self):
        with self._lock: self._cache.clear()

class RobustDependencyAnalyzer: # Inalterada (a lógica de resolver imports ainda é necessária para os parsers AST)
    def __init__(self, project_root: str, progress_callback: Callable[[str], None]):
        self.project_root = os.path.abspath(project_root)
        self.progress_callback = progress_callback
        self.cache = DependencyCache()
        self.file_stats: Dict[str, int] = defaultdict(int)
    def clean_code_content(self, content: str, file_ext: str) -> str:
        if not content.strip(): return ""
        patterns = COMMENT_PATTERNS.get(file_ext.lower(), [])
        cleaned = content
        for p, flags in patterns:
            try: cleaned = p.sub('', cleaned)
            except re.error as e: self.progress_callback(f"WARN: Regex error for {file_ext}: {e}")
        cleaned = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned)
        cleaned = re.sub(r'[ \t]+\n', '\n', cleaned)
        return cleaned.strip()
    def normalize_path(self, p_str: str, base_d: str = "") -> Optional[str]:
        try:
            abs_p = os.path.abspath(os.path.join(self.project_root, base_d, p_str)) if base_d \
                    else os.path.abspath(os.path.join(self.project_root, p_str))
            if not abs_p.startswith(self.project_root): return None
            return os.path.normpath(os.path.relpath(abs_p, self.project_root)).replace('\\', '/')
        except (ValueError, OSError): return None
    def resolve_import_with_fallbacks(self, raw_imp: str, res_type: str, curr_f_dir: str, all_fs: Set[str]) -> Set[str]:
        # Esta função e seus helpers (_resolve_python_import, etc.) permanecem como estão,
        # pois são usados internamente pelos parsers AST para resolver os caminhos que eles encontram.
        # A mudança principal é que não haverá mais um fallback GERAL para regex se um parser AST não existir.
        # As implementações de _resolve_... são as mesmas da sua versão anterior.
        resolved: Set[str] = set()
        try:
            if res_type == 'python_module': resolved.update(self._resolve_python_import(raw_imp, curr_f_dir, all_fs))
            elif res_type in ['relative_path_js', 'relative_path_ts']: resolved.update(self._resolve_js_import(raw_imp, curr_f_dir, all_fs, res_type))
            elif res_type == 'relative_path_c': resolved.update(self._resolve_c_import(raw_imp, curr_f_dir, all_fs))
            elif res_type == 'relative_path_html_resource': resolved.update(self._resolve_html_resource(raw_imp, curr_f_dir, all_fs))
            # Java não é mais "robustamente" suportado para dependências, então o resolver_type 'java_package'
            # não será chamado a menos que um parser AST futuro o use.
        except Exception as e: self.progress_callback(f"WARN: Error resolving import '{raw_imp}' type '{res_type}': {e}")
        return resolved
    def _resolve_python_import(self, import_str: str, current_dir: str, all_files: Set[str]) -> Set[str]:
        resolved: Set[str] = set(); parts = import_str.split('.'); module_path_parts = []
        if import_str.startswith('.'):
            level = 0
            while parts and parts[0] == '': level += 1; parts.pop(0)
            current_parts = current_dir.split('/') if current_dir and current_dir != "." else []
            if level -1 > len(current_parts): return resolved
            base_parts = current_parts[:-(level-1)] if level > 1 else current_parts
            module_path_parts = base_parts + parts
        else: module_path_parts = import_str.replace('.', '/').split('/')
        module_base_path = '/'.join(filter(None, module_path_parts))
        candidates = [f"{module_base_path}.py", f"{module_base_path}/__init__.py"]
        for candidate in candidates:
            normalized = self.normalize_path(candidate)
            if normalized and normalized in all_files: resolved.add(normalized)
        return resolved
    def _resolve_js_import(self, import_str: str, current_dir: str, all_files: Set[str], resolver_type: str) -> Set[str]:
        resolved: Set[str] = set()
        if not (import_str.startswith(('./', '../', '/'))):
            if '/' not in import_str:
                for ext_js in ['.js', '.jsx', '.ts', '.tsx', '.json']:
                    cand_js = self.normalize_path(f"{import_str}{ext_js}")
                    if cand_js and cand_js in all_files: resolved.add(cand_js)
                if not resolved: return resolved
            else: current_dir = "" 
        base_path_js = import_str; exts_js = ['.js', '.jsx', '.ts', '.tsx', '.json']
        cands_paths_js = [base_path_js]
        if not any(base_path_js.endswith(e) for e in exts_js): cands_paths_js.extend([f"{base_path_js}{e}" for e in exts_js])
        idx_exts_js = ['.js', '.jsx', '.ts', '.tsx'] if resolver_type in ['relative_path_js', 'relative_path_ts'] else []
        for e_idx_js in idx_exts_js: cands_paths_js.append(f"{base_path_js}/index{e_idx_js}")
        for cand_p_js in cands_paths_js:
            norm_p_js = self.normalize_path(cand_p_js, current_dir)
            if norm_p_js and norm_p_js in all_files: resolved.add(norm_p_js)
        return resolved
    def _resolve_c_import(self, include_str: str, current_dir: str, all_files: Set[str]) -> Set[str]:
        resolved: Set[str] = set()
        cand_curr_c = self.normalize_path(include_str, current_dir)
        if cand_curr_c and cand_curr_c in all_files: resolved.add(cand_curr_c)
        cand_root_c = self.normalize_path(include_str)
        if cand_root_c and cand_root_c in all_files: resolved.add(cand_root_c)
        return resolved
    def _resolve_html_resource(self, resource_str: str, current_dir: str, all_files: Set[str]) -> Set[str]:
        resolved: Set[str] = set()
        if resource_str.startswith(('http:', 'https:', '//', 'data:')): return resolved
        norm_html = self.normalize_path(resource_str, current_dir)
        if norm_html and norm_html in all_files: resolved.add(norm_html)
        elif '.' not in os.path.basename(resource_str):
            common_exts_html = ['.js', '.css', '.html', '.png', '.jpg', '.svg']
            for ext_add_html in common_exts_html:
                norm_ext_html = self.normalize_path(resource_str + ext_add_html, current_dir)
                if norm_ext_html and norm_ext_html in all_files: resolved.add(norm_ext_html); break
        return resolved
    # _resolve_java_import não é mais necessário aqui, pois Java não tem parser AST e não faremos fallback regex.


# Analisadores AST - Python, JS, C/C++, HTML (Inalterados em sua lógica interna)
class ASTPythonAnalyzer(ast.NodeVisitor): # Inalterada
    def __init__(self): self.imports: Set[str] = set()
    def visit_Import(self, node: ast.Import):
        for alias in node.names: self.imports.add(alias.name)
        self.generic_visit(node)
    def visit_ImportFrom(self, node: ast.ImportFrom):
        module_name = node.module
        if node.level > 0: prefix = '.' * node.level; full_name = prefix + module_name if module_name else prefix; self.imports.add(full_name)
        elif module_name: self.imports.add(module_name)
        self.generic_visit(node)
    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == '__import__' and \
           node.args and isinstance(node.args[0], (ast.Str, ast.Constant) ):
            val = node.args[0].s if isinstance(node.args[0], ast.Str) else node.args[0].value
            if isinstance(val, str): self.imports.add(val)
        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and \
             node.func.value.id == 'importlib' and node.func.attr == 'import_module' and \
             node.args and isinstance(node.args[0], (ast.Str, ast.Constant) ):
            val = node.args[0].s if isinstance(node.args[0], ast.Str) else node.args[0].value
            if isinstance(val, str): self.imports.add(val)
        self.generic_visit(node)
def analyze_dependencies_python_ast(fp: str, ct: str, an: RobustDependencyAnalyzer, afs: Set[str]) -> Set[str]: # Inalterada
    deps: Set[str] = set(); cd = os.path.dirname(fp) if os.path.dirname(fp) else ""
    try:
        tree = ast.parse(ct, filename=fp); v = ASTPythonAnalyzer(); v.visit(tree)
        for imp_s in v.imports:
            rps = an.resolve_import_with_fallbacks(imp_s, 'python_module', cd, afs)
            for rpi in rps:
                if rpi != fp: deps.add(rpi)
    except SyntaxError as e_s: an.progress_callback(f"WARN: Python AST SyntaxError {fp}: {e_s}")
    except Exception as e_g: an.progress_callback(f"ERROR: Python AST analysis failure for {fp}: {e_g}")
    return deps
def extract_js_imports_from_ast_node(node) -> Set[str]: # Inalterada
    imps: Set[str] = set()
    if isinstance(node, dict):
        nt = node.get('type'); sv = None
        if nt == 'ImportDeclaration' and node.get('source') and isinstance(node['source'].get('value'), str): sv = node['source']['value']
        elif nt == 'ExportNamedDeclaration' and node.get('source') and isinstance(node['source'].get('value'), str): sv = node['source']['value']
        elif nt == 'ExportAllDeclaration' and node.get('source') and isinstance(node['source'].get('value'), str): sv = node['source']['value']
        elif nt == 'CallExpression':
            cl = node.get('callee', {}); is_rq = cl.get('type') == 'Identifier' and cl.get('name') == 'require'; is_di = cl.get('type') == 'Import'
            if is_rq or is_di:
                ag = node.get('arguments', [])
                if ag and len(ag) > 0 and isinstance(ag[0], dict) and ag[0].get('type') == 'Literal' and isinstance(ag[0].get('value'), str): sv = ag[0]['value']
        if sv: imps.add(sv)
        for v_item in node.values(): imps.update(extract_js_imports_from_ast_node(v_item))
    elif isinstance(node, list):
        for l_item in node: imps.update(extract_js_imports_from_ast_node(l_item))
    return imps
def analyze_dependencies_js_ast(fp: str, ct: str, an: RobustDependencyAnalyzer, afs: Set[str]) -> Set[str]: # Inalterada
    if not PYJSPARSER_AVAILABLE: return set()
    deps: Set[str] = set(); cd = os.path.dirname(fp) if os.path.dirname(fp) else ""
    try:
        ast_t_js = pyjsparser.parse(ct); raw_i_js = extract_js_imports_from_ast_node(ast_t_js)
        res_t_js = 'relative_path_ts' if fp.lower().endswith(('.ts', '.tsx')) else 'relative_path_js'
        for i_s_js in raw_i_js:
            res_p_js = an.resolve_import_with_fallbacks(i_s_js, res_t_js, cd, afs)
            for rp_i_js in res_p_js:
                if rp_i_js != fp: deps.add(rp_i_js)
    except Exception as e_j: an.progress_callback(f"WARN: JS/TS AST Parser error for {fp}: {e_j}")
    return deps
def analyze_dependencies_c_cpp_ast(fp: str, ct: str, an: RobustDependencyAnalyzer, afs: Set[str]) -> Set[str]: # Inalterada
    if not LIBCLANG_AVAILABLE: return set()
    deps: Set[str] = set(); cd_r_c = os.path.dirname(fp) if os.path.dirname(fp) else ""; cf_a_c = os.path.join(an.project_root, fp)
    l_o_c = '-x c++' if fp.lower().endswith(('.cpp', '.cxx', '.hpp', '.hxx')) else '-x c'
    cla_args_c = [f'-I{os.path.dirname(cf_a_c)}', f'-I{an.project_root}', l_o_c]
    try:
        idx_c_c = cindex.Index.create()
        tu_cc = idx_c_c.parse(cf_a_c, args=cla_args_c, options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD | cindex.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES)
        for cn_c in tu_cc.cursor.get_children():
            if cn_c.kind == cindex.CursorKind.INCLUSION_DIRECTIVE:
                inc_f_r_c = cn_c.displayname; res_cl_p_c = None
                try:
                    if cn_c.get_included_file() and cn_c.get_included_file().name.startswith(an.project_root):
                        res_cl_p_c = os.path.relpath(cn_c.get_included_file().name, an.project_root).replace('\\', '/')
                except Exception: pass
                if res_cl_p_c and res_cl_p_c in afs and res_cl_p_c != fp: deps.add(res_cl_p_c)
                else:
                    res_m_c = an.resolve_import_with_fallbacks(inc_f_r_c, 'relative_path_c', cd_r_c, afs)
                    for rp_c_i in res_m_c:
                        if rp_c_i != fp: deps.add(rp_c_i)
    except cindex.LibclangError as e_clg: an.progress_callback(f"ERROR: Libclang error for {fp}: {e_clg}")
    except Exception as e_c_g: an.progress_callback(f"ERROR: C/C++ AST analysis failure for {fp}: {e_c_g}")
    return deps
def analyze_dependencies_html_ast(fp: str, ct: str, an: RobustDependencyAnalyzer, afs: Set[str]) -> Set[str]: # Inalterada
    if not BEAUTIFULSOUP_AVAILABLE: return set()
    deps: Set[str] = set(); cd_h = os.path.dirname(fp) if os.path.dirname(fp) else ""
    try:
        sp_h = BeautifulSoup(ct, 'lxml'); tg_at_h = [('script', 'src'), ('link', 'href')]
        for tgn_h, atn_h in tg_at_h:
            for tnode_h in sp_h.find_all(tgn_h):
                res_v_h = tnode_h.get(atn_h)
                if isinstance(res_v_h, str) and res_v_h.strip():
                    if tgn_h == 'link' and not ('stylesheet' in (tnode_h.get('rel') or [])): continue
                    res_p_h = an.resolve_import_with_fallbacks(res_v_h, 'relative_path_html_resource', cd_h, afs)
                    for rp_h_i in res_p_h:
                        if rp_h_i != fp: deps.add(rp_h_i)
    except Exception as e_h: an.progress_callback(f"ERROR: HTML analysis failure for {fp}: {e_h}")
    return deps

AST_PARSERS_MAP: Dict[str, Callable] = {
    '.py': analyze_dependencies_python_ast, '.pyw': analyze_dependencies_python_ast,
    '.js': analyze_dependencies_js_ast, '.jsx': analyze_dependencies_js_ast,
    '.ts': analyze_dependencies_js_ast, '.tsx': analyze_dependencies_js_ast,
    '.c': analyze_dependencies_c_cpp_ast, '.cpp': analyze_dependencies_c_cpp_ast, '.cxx': analyze_dependencies_c_cpp_ast,
    '.h': analyze_dependencies_c_cpp_ast, '.hpp': analyze_dependencies_c_cpp_ast, '.hxx': analyze_dependencies_c_cpp_ast,
    '.html': analyze_dependencies_html_ast, '.htm': analyze_dependencies_html_ast,
}

def _analyze_single_file_deps_task(file_info: FileInfo, analyzer: RobustDependencyAnalyzer, all_project_files_set: Set[str]) -> Tuple[str, Set[str], str, Optional[str]]:
    if file_info.path in analyzer.cache._cache:
        deps_c = analyzer.cache.get(file_info.path)
        return file_info.path, deps_c, "success (cached)", None

    # A verificação se a extensão é suportada para análise de dependência AST
    # agora é implícita pelo fato de apenas chamarmos parser_func se ele existir.
    # ALL_EFFECTIVELY_SUPPORTED_EXTENSIONS é usado no início do process_project_folder.
    parser_func = AST_PARSERS_MAP.get(file_info.ext)
    if parser_func:
        analyzer.file_stats[f"ast_{file_info.ext}"] += 1
        deps_f = parser_func(file_info.path, file_info.original_content, analyzer, all_project_files_set)
        analyzer.cache.set(file_info.path, deps_f)
        return file_info.path, deps_f, "success", None
    else:
        # Este arquivo não tem um parser AST definido, então suas dependências não são analisadas.
        analyzer.file_stats[f"skipped_dep_analysis_{file_info.ext}"] += 1
        analyzer.cache.set(file_info.path, set())
        return file_info.path, set(), "skipped (no AST parser)", None

def get_transitive_dependencies_for_file(target_fp: str, all_finfo_map: Dict[str, FileInfo],
                                       analyzer: RobustDependencyAnalyzer, all_proj_files_set: Set[str],
                                       max_depth: int = 20) -> Set[str]: # Inalterada na lógica principal
    memo_tr: Dict[str, Set[str]] = {}
    def _recursive_get_trans(curr_fp: str, visited_ps: Set[str], curr_d: int) -> Set[str]:
        if curr_fp in visited_ps or curr_d > max_depth: return set()
        if curr_fp in memo_tr: return memo_tr[curr_fp]
        visited_ps.add(curr_fp)
        finfo_o = all_finfo_map.get(curr_fp)
        if not finfo_o: memo_tr[curr_fp] = set(); return set()
        if finfo_o.direct_dependencies is None or finfo_o.dependency_analysis_status == "pending":
            _pth, dds, sts, err_m = _analyze_single_file_deps_task(finfo_o, analyzer, all_proj_files_set)
            finfo_o.direct_dependencies = dds; finfo_o.dependency_analysis_status = sts; finfo_o.dependency_analysis_error = err_m
        curr_trans_ds = set(finfo_o.direct_dependencies)
        for dep_p_i in finfo_o.direct_dependencies:
            if dep_p_i in all_finfo_map:
                curr_trans_ds.update(_recursive_get_trans(dep_p_i, visited_ps.copy(), curr_d + 1))
        memo_tr[curr_fp] = curr_trans_ds
        return curr_trans_ds
    all_trans_ds_val = _recursive_get_trans(target_fp, set(), 0)
    target_finfo_o = all_finfo_map.get(target_fp)
    if target_finfo_o: target_finfo_o.transitive_dependencies = all_trans_ds_val
    return all_trans_ds_val

def get_project_structure_display(src_dir_abs: str, rel_file_paths: List[str]) -> str: # Inalterada
    if not rel_file_paths: return "No relevant files found in the project."
    s_lines = ["Project Structure:", ""]; t_root: Dict = {}
    for rel_p_s_val in sorted(list(set(rel_file_paths))):
        p_obj_val = Path(rel_p_s_val); curr_l_d_val = t_root
        for part_n_val in p_obj_val.parts: curr_l_d_val = curr_l_d_val.setdefault(part_n_val, {})
    def _gen_tree_lines_rec(curr_n_d_val: dict, curr_pref_val: str = "") -> List[str]:
        out_l_val: List[str] = []
        sorted_i_ns_val = sorted(curr_n_d_val.keys(), key=lambda k_val: (not bool(curr_n_d_val[k_val]), k_val))
        for i_val, item_n_s_val in enumerate(sorted_i_ns_val):
            is_last_i_val = (i_val == len(sorted_i_ns_val) - 1)
            conn_c_val = "└── " if is_last_i_val else "├── "
            out_l_val.append(f"{curr_pref_val}{conn_c_val}{item_n_s_val}")
            if curr_n_d_val[item_n_s_val]:
                new_p_ext_val = "    " if is_last_i_val else "│   "
                out_l_val.extend(_gen_tree_lines_rec(curr_n_d_val[item_n_s_val], curr_pref_val + new_p_ext_val))
        return out_l_val
    s_lines.extend(_gen_tree_lines_rec(t_root))
    return "\n".join(s_lines)

MAX_THREADS = os.cpu_count() or 4

def process_project_folder(source_dir: str, dest_dir: str, 
                           selected_lang_extensions_ui: Set[str], # Extensões selecionadas na UI
                           progress_callback_ui: Callable[[str], str]
                           ) -> Tuple[List[str], int]:
    
    logs_list: List[str] = []
    txt_count: int = 0
    
    processed_ext_stats = Counter() # Para rastrear arquivos processados por extensão
    skipped_ext_stats = Counter()   # Para rastrear arquivos encontrados mas não selecionados/suportados

    def _log_ui(msg: str, is_err: bool = False) -> str:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        logs_list.append(f"[{ts}] {msg}"); progress_callback_ui(msg) 
        return ts

    _log_ui(f"INFO: Processing project: {source_dir}")
    analyzer_inst = RobustDependencyAnalyzer(project_root=source_dir, progress_callback=lambda m: _log_ui(f"ANALYZER: {m}"))
    analyzer_inst.cache.clear()

    all_files_map: Dict[str, FileInfo] = {}
    project_scan_rel_paths: List[str] = []

    _log_ui("INFO: Scanning project files...")
    for root_p, sub_ds, files_in_d in os.walk(source_dir, topdown=True):
        sub_ds[:] = [dn for dn in sub_ds if dn not in IGNORED_ITEMS and 
                     not any(fnmatch(dn, pat_i) for pat_i in IGNORED_ITEMS if '*' in pat_i or '?' in pat_i)]
        for file_nm in files_in_d:
            if file_nm in IGNORED_ITEMS or \
               any(fnmatch(file_nm, pat_i) for pat_i in IGNORED_ITEMS if '*' in pat_i or '?' in pat_i):
                skipped_ext_stats['ignored_item'] += 1
                continue
            
            file_abs = os.path.join(root_p, file_nm)
            rel_file = os.path.relpath(file_abs, source_dir).replace('\\', '/')
            _fn_part_val, file_e_val = os.path.splitext(file_nm)
            file_e_l_val = file_e_val.lower()

            # Verifica se a extensão está na lista de *efetivamente suportadas* (ALL_EFFECTIVELY_SUPPORTED_EXTENSIONS)
            # E se também foi selecionada na UI (selected_lang_extensions_ui)
            if file_e_l_val in ALL_EFFECTIVELY_SUPPORTED_EXTENSIONS and file_e_l_val in selected_lang_extensions_ui:
                project_scan_rel_paths.append(rel_file)
                processed_ext_stats[file_e_l_val] += 1
                try:
                    with open(file_abs, 'r', encoding='utf-8', errors='ignore') as f_in_h:
                        orig_c = f_in_h.read()
                    cleaned_c = analyzer_inst.clean_code_content(orig_c, file_e_l_val)
                    f_s_info = os.stat(file_abs)
                    all_files_map[rel_file] = FileInfo(
                        path=rel_file, content=cleaned_c, original_content=orig_c, original_name=file_nm,
                        ext=file_e_l_val, size=f_s_info.st_size, last_modified=f_s_info.st_mtime
                    )
                except Exception as e_read_f:
                    _log_ui(f"ERROR: Failed to read/process file {rel_file}: {e_read_f}", is_err=True)
            elif file_e_l_val in selected_lang_extensions_ui: # Selecionado na UI, mas não em ALL_EFFECTIVELY_SUPPORTED_EXTENSIONS
                skipped_ext_stats[f"{file_e_l_val} (selected_but_not_robust)"] +=1
            else: # Não selecionado na UI ou não suportado
                skipped_ext_stats[file_e_l_val] +=1


    if not all_files_map:
        _log_ui("WARN: No files matching supported and selected extensions found for processing.")
        return logs_list, 0

    _log_ui(f"INFO: {len(all_files_map)} files identified for robust processing. Analyzing dependencies...")
    all_proj_files_s = set(all_files_map.keys())

    with ThreadPoolExecutor(max_workers=MAX_THREADS) as exec_d:
        fut_to_p_d = {
            exec_d.submit(_analyze_single_file_deps_task, finfo_o, analyzer_inst, all_proj_files_s): fp_k
            for fp_k, finfo_o in all_files_map.items()
        }
        for i_dd, comp_f_d in enumerate(as_completed(fut_to_p_d)):
            fin_fpd = fut_to_p_d[comp_f_d]
            try:
                _p_r, d_d_r, st_r, err_m_r = comp_f_d.result()
                all_files_map[fin_fpd].direct_dependencies = d_d_r
                all_files_map[fin_fpd].dependency_analysis_status = st_r
                all_files_map[fin_fpd].dependency_analysis_error = err_m_r
            except Exception as e_d_t_e:
                _log_ui(f"ERROR: Task for direct deps of {fin_fpd} failed: {e_d_t_e}", is_err=True)
                all_files_map[fin_fpd].dependency_analysis_status = "error (task_direct_fatal)"
                all_files_map[fin_fpd].dependency_analysis_error = str(e_d_t_e)
            if (i_dd + 1) % (len(all_files_map) // 20 or 1) == 0:
                 _log_ui(f"INFO: Direct dependencies analyzed for {i_dd+1}/{len(all_files_map)} files.")
    
    _log_ui("INFO: Direct dependency analysis complete. Calculating transitive dependencies...")
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as exec_t:
        fut_to_p_t = {
            exec_t.submit(get_transitive_dependencies_for_file, 
                           fp_k_t, all_files_map, analyzer_inst, all_proj_files_s): fp_k_t
            for fp_k_t in all_files_map.keys()
        }
        for i_tt, comp_f_t in enumerate(as_completed(fut_to_p_t)):
            fin_fp_tt = fut_to_p_t[comp_f_t]
            try: _ = comp_f_t.result() 
            except Exception as e_t_t_e:
                 _log_ui(f"ERROR: Task for transitive deps of {fin_fp_tt} failed: {e_t_t_e}", is_err=True)
                 if fin_fp_tt in all_files_map: all_files_map[fin_fp_tt].dependency_analysis_status += " (transitive_task_fatal)"
            if (i_tt + 1) % (len(all_files_map) // 20 or 1) == 0:
                _log_ui(f"INFO: Transitive dependencies calculated for {i_tt+1}/{len(all_files_map)} files.")

    _log_ui("INFO: Full dependency analysis complete.")
    for sk, sc in analyzer_inst.file_stats.items(): _log_ui(f"STATS: Analyzer {sk} used {sc} times.")

    proj_s_str = get_project_structure_display(analyzer_inst.project_root, project_scan_rel_paths)
    _log_ui("INFO: Generating context output files...")
    os.makedirs(dest_dir, exist_ok=True)
    
    main_fname = "_PROJECT_OVERVIEW_CONTEXT.txt"; main_fpath = os.path.join(dest_dir, main_fname)
    try:
        with open(main_fpath, 'w', encoding='utf-8') as f_o_m:
            tsm = _log_ui(""); f_o_m.write(f"AI CONTEXT - PROJECT OVERVIEW\n")
            f_o_m.write(f"Project Root: {analyzer_inst.project_root}\nGenerated at: {tsm}\n")
            f_o_m.write("=" * 80 + "\n"); f_o_m.write(proj_s_str + "\n\n"); f_o_m.write("=" * 80 + "\n")
            f_o_m.write("ALL PROCESSED SOURCE FILES IN PROJECT:\n"); f_o_m.write("=" * 80 + "\n")
            for ps_s in sorted(project_scan_rel_paths): f_o_m.write(f"- {ps_s}\n")
            f_o_m.write("\n")
        _log_ui(f"SUCCESS: Main project overview file generated: {main_fname}"); txt_count += 1
    except Exception as e_mo: _log_ui(f"ERROR: Failed to generate main overview file {main_fpath}: {e_mo}", is_err=True)

    for i_out_idx, (rel_pk, finfo_data_obj) in enumerate(all_files_map.items()):
        out_bn = finfo_data_obj.original_name; out_tn = f"{out_bn}.txt"
        f_dir_rel = os.path.dirname(rel_pk)
        out_f_dir_p = os.path.join(dest_dir, f_dir_rel); os.makedirs(out_f_dir_p, exist_ok=True)
        out_f_fp = os.path.join(out_f_dir_p, out_tn)
        try:
            with open(out_f_fp, 'w', encoding='utf-8') as f_o_i:
                ts_fi = _log_ui("")
                f_o_i.write(f"AI CONTEXT - Source File Focus: {finfo_data_obj.path}\n")
                f_o_i.write(f"Project Root: {analyzer_inst.project_root}\nGenerated at: {ts_fi}\n")
                f_o_i.write("=" * 80 + "\n"); f_o_i.write(proj_s_str + "\n\n"); f_o_i.write("=" * 80 + "\n")
                f_o_i.write(f"FOCUSED FILE CONTENT: {finfo_data_obj.path}\n")
                f_o_i.write(f"(Dependency Analysis Status: {finfo_data_obj.dependency_analysis_status})\n")
                if finfo_data_obj.dependency_analysis_error: f_o_i.write(f"(Analysis Error: {finfo_data_obj.dependency_analysis_error})\n")
                f_o_i.write("=" * 80 + "\n"); f_o_i.write(finfo_data_obj.content + "\n\n")
                deps_inc = finfo_data_obj.transitive_dependencies or set()
                if deps_inc:
                    f_o_i.write("=" * 80 + "\n"); f_o_i.write("DEPENDENT FILES' CONTENT (intra-project):\n"); f_o_i.write("=" * 80 + "\n\n")
                    for dep_ps in sorted(list(deps_inc)):
                        if dep_ps in all_files_map:
                            dep_fio = all_files_map[dep_ps]
                            f_o_i.write(f"--- FILE (Dependency): {dep_fio.path} ---\n"); f_o_i.write(dep_fio.content + "\n\n")
                else:
                    f_o_i.write("=" * 80 + "\n"); f_o_i.write("No intra-project file dependencies identified or analysis skipped/error.\n"); f_o_i.write("=" * 80 + "\n\n")
            if (i_out_idx + 1) % (len(all_files_map) // 10 or 1) == 0:
                 _log_ui(f"SUCCESS: Generated {i_out_idx + 1}/{len(all_files_map)} individual context files.")
            txt_count += 1
        except Exception as e_io: _log_ui(f"ERROR: Failed to generate context file {out_f_fp}: {e_io}", is_err=True)
    
    # Relatório de Processamento de Arquivos
    _log_ui("--- FILE PROCESSING SUMMARY ---")
    if processed_ext_stats:
        _log_ui("Files Processed (by extension):")
        for ext_p, count_p in processed_ext_stats.items():
            _log_ui(f"  - {ext_p}: {count_p} file(s)")
    else:
        _log_ui("No files were processed based on selection and support.")
    
    if skipped_ext_stats:
        _log_ui("Files Skipped or Ignored (by extension/reason):")
        for ext_s, count_s in skipped_ext_stats.items():
            _log_ui(f"  - {ext_s}: {count_s} file(s)")
            
    _log_ui(f"INFO: Processing complete. Total {txt_count} TXT files generated.")
    return logs_list, txt_count