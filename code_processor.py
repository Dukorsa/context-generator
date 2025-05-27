import os
import re
import sys
from fnmatch import fnmatch
import ast
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
from typing import Set, Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
from collections import defaultdict, Counter

# --- Configuração e Verificação de Disponibilidade de Bibliotecas Opcionais ---

_libclang_path_found_by_config = False
LIBCLANG_AVAILABLE = False

# Tenta configurar o caminho para libclang se estiver rodando de um bundle PyInstaller
# ou se um caminho específico for fornecido via variável de ambiente para desenvolvimento.
if hasattr(sys, '_MEIPASS'): # Rodando em um bundle PyInstaller
    lib_names = []
    if sys.platform == "win32":
        lib_names = ["libclang.dll"]
    elif sys.platform == "darwin":
        lib_names = ["libclang.dylib"]
    else: # Assumindo Linux ou outros Unix-like
        lib_names = ["libclang.so"]

    # Adicionar aqui nomes versionados se necessário (ex: libclang-10.dll)

    search_dirs = [
        sys._MEIPASS,
        os.path.join(sys._MEIPASS, 'lib'),
        os.path.join(sys._MEIPASS, 'clang') # Alguns hooks podem colocar aqui
    ]

    for search_dir in search_dirs:
        if _libclang_path_found_by_config: break
        for lib_name in lib_names:
            potential_path = os.path.join(search_dir, lib_name)
            if os.path.exists(potential_path):
                try:
                    from clang.cindex import Config
                    Config.set_library_file(potential_path)
                    _libclang_path_found_by_config = True
                    # print(f"INFO: libclang carregada de: {potential_path}") # Log para depuração
                    break
                except Exception as e_cfg:
                    pass # print(f"WARN: Falha ao configurar libclang de {potential_path}: {e_cfg}")
            # else:
            #     print(f"DEBUG: libclang não encontrada em {potential_path}") # Log para depuração
    # if not _libclang_path_found_by_config:
        # print("ALERTA: Não foi possível encontrar ou configurar libclang no bundle PyInstaller.") # Log para depuração

# Tenta importar clang.cindex e verificar funcionalidade
try:
    from clang import cindex
    try:
        cindex.Index.create() # Tenta carregar a biblioteca
        LIBCLANG_AVAILABLE = True
        # if not _libclang_path_found_by_config and hasattr(sys, '_MEIPASS'):
        #      print("INFO: LIBCLANG_AVAILABLE=True, mas _libclang_path_found_by_config=False.") # Log para depuração
        # elif not _libclang_path_found_by_config:
        #      print("INFO: LIBCLANG_AVAILABLE=True (provavelmente do PATH do sistema).") # Log para depuração
    except cindex.LibclangError:
        LIBCLANG_AVAILABLE = False
    except Exception: # Outras exceções
        LIBCLANG_AVAILABLE = False
except ImportError:
    LIBCLANG_AVAILABLE = False


try:
    import pyjsparser
    PYJSPARSER_AVAILABLE = True
except ImportError:
    PYJSPARSER_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BEAUTIFULSOUP_AVAILABLE = True
except ImportError:
    BEAUTIFULSOUP_AVAILABLE = False

# Importações do projeto
from config import COMMENT_PATTERNS, IGNORED_ITEMS, SUPPORTED_LANGUAGES, ALL_EFFECTIVELY_SUPPORTED_EXTENSIONS

@dataclass
class FileInfo:
    path: str
    content: str
    original_content: str
    original_name: str
    ext: str
    size: int
    last_modified: float
    direct_dependencies: Set[str] = field(default_factory=set)
    transitive_dependencies: Set[str] = field(default_factory=set)
    dependency_analysis_status: str = "pending"
    dependency_analysis_error: Optional[str] = None

class DependencyCache:
    def __init__(self):
        self._cache: Dict[str, Set[str]] = {}
        self._lock = threading.Lock()

    def get(self, fp: str) -> Optional[Set[str]]:
        with self._lock:
            return self._cache.get(fp)

    def set(self, fp: str, deps: Set[str]):
        with self._lock:
            self._cache[fp] = deps.copy()

    def clear(self):
        with self._lock:
            self._cache.clear()

class RobustDependencyAnalyzer:
    def __init__(self, project_root: str, progress_callback: Callable[[str], None]):
        self.project_root = os.path.abspath(project_root)
        self.progress_callback = progress_callback
        self.cache = DependencyCache()
        self.file_stats: Dict[str, int] = defaultdict(int) # Estatísticas de uso de analisadores

    def clean_code_content(self, content: str, file_ext: str) -> str:
        if not content.strip():
            return ""
        patterns = COMMENT_PATTERNS.get(file_ext.lower(), [])
        cleaned = content
        for p, flags in patterns: # flags não é usado, mas mantido para compatibilidade com o formato de COMMENT_PATTERNS
            try:
                cleaned = p.sub('', cleaned)
            except re.error as e:
                self.progress_callback(f"WARN: Regex error for {file_ext}: {e}")
        cleaned = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned) # Reduz múltiplas linhas em branco
        cleaned = re.sub(r'[ \t]+\n', '\n', cleaned) # Remove espaços/tabs no final das linhas
        return cleaned.strip()

    def normalize_path(self, p_str: str, base_d: str = "") -> Optional[str]:
        try:
            if base_d:
                abs_p = os.path.abspath(os.path.join(self.project_root, base_d, p_str))
            else:
                abs_p = os.path.abspath(os.path.join(self.project_root, p_str))

            if not abs_p.startswith(self.project_root): # Garante que o caminho está dentro do projeto
                return None
            return os.path.normpath(os.path.relpath(abs_p, self.project_root)).replace('\\', '/')
        except (ValueError, OSError):
            return None

    def resolve_import_with_fallbacks(self, raw_imp: str, res_type: str, curr_f_dir: str, all_fs: Set[str]) -> Set[str]:
        # Resolve diferentes tipos de declarações de import/include para caminhos de arquivo normalizados.
        resolved: Set[str] = set()
        try:
            if res_type == 'python_module':
                resolved.update(self._resolve_python_import(raw_imp, curr_f_dir, all_fs))
            elif res_type in ['relative_path_js', 'relative_path_ts']:
                resolved.update(self._resolve_js_import(raw_imp, curr_f_dir, all_fs, res_type))
            elif res_type == 'relative_path_c':
                resolved.update(self._resolve_c_import(raw_imp, curr_f_dir, all_fs))
            elif res_type == 'relative_path_html_resource':
                resolved.update(self._resolve_html_resource(raw_imp, curr_f_dir, all_fs))
        except Exception as e:
            self.progress_callback(f"WARN: Error resolving import '{raw_imp}' type '{res_type}': {e}")
        return resolved

    def _resolve_python_import(self, import_str: str, current_dir: str, all_files: Set[str]) -> Set[str]:
        resolved: Set[str] = set()
        parts = import_str.split('.')
        module_path_parts = []

        if import_str.startswith('.'): # Import relativo
            level = 0
            while parts and parts[0] == '':
                level += 1
                parts.pop(0)
            current_parts = current_dir.split('/') if current_dir and current_dir != "." else []
            if level -1 > len(current_parts): return resolved # Tentativa de ir além da raiz do pacote
            base_parts = current_parts[:-(level-1)] if level > 1 else current_parts
            module_path_parts = base_parts + parts
        else: # Import absoluto
            module_path_parts = import_str.replace('.', '/').split('/')

        module_base_path = '/'.join(filter(None, module_path_parts))
        candidates = [
            f"{module_base_path}.py",       # arquivo.py
            f"{module_base_path}/__init__.py" # pacote/
        ]
        for candidate in candidates:
            normalized = self.normalize_path(candidate)
            if normalized and normalized in all_files:
                resolved.add(normalized)
        return resolved

    def _resolve_js_import(self, import_str: str, current_dir: str, all_files: Set[str], resolver_type: str) -> Set[str]:
        resolved: Set[str] = set()
        # Trata imports de node_modules (bare specifiers) ou imports absolutos (iniciando com /)
        if not (import_str.startswith(('./', '../', '/'))):
            if '/' not in import_str: # Pode ser um módulo (ex: 'react') ou um arquivo local sem ./
                # Tenta resolver como arquivo local primeiro, sem considerar node_modules aqui
                for ext_js in ['.js', '.jsx', '.ts', '.tsx', '.json']:
                    cand_js = self.normalize_path(f"{import_str}{ext_js}")
                    if cand_js and cand_js in all_files: resolved.add(cand_js)
                if not resolved: return resolved # Não encontrado como arquivo local
            else: # Ex: 'some/module/file.js', interpretado como a partir da raiz do projeto
                current_dir = "" # Reset current_dir para resolver a partir da raiz do projeto

        base_path_js = import_str
        exts_js = ['.js', '.jsx', '.ts', '.tsx', '.json']
        cands_paths_js = [base_path_js]
        # Adiciona extensões se não estiverem presentes
        if not any(base_path_js.endswith(e) for e in exts_js):
            cands_paths_js.extend([f"{base_path_js}{e}" for e in exts_js])
        # Adiciona /index.js, /index.ts etc. para imports de diretório
        idx_exts_js = ['.js', '.jsx', '.ts', '.tsx'] if resolver_type in ['relative_path_js', 'relative_path_ts'] else []
        for e_idx_js in idx_exts_js:
            cands_paths_js.append(f"{base_path_js}/index{e_idx_js}")

        for cand_p_js in cands_paths_js:
            norm_p_js = self.normalize_path(cand_p_js, current_dir)
            if norm_p_js and norm_p_js in all_files:
                resolved.add(norm_p_js)
        return resolved

    def _resolve_c_import(self, include_str: str, current_dir: str, all_files: Set[str]) -> Set[str]:
        resolved: Set[str] = set()
        # Tenta resolver relativo ao arquivo atual
        cand_curr_c = self.normalize_path(include_str, current_dir)
        if cand_curr_c and cand_curr_c in all_files:
            resolved.add(cand_curr_c)
        # Tenta resolver relativo à raiz do projeto (para includes como <stdio.h> que podem ser locais)
        cand_root_c = self.normalize_path(include_str)
        if cand_root_c and cand_root_c in all_files:
            resolved.add(cand_root_c)
        return resolved

    def _resolve_html_resource(self, resource_str: str, current_dir: str, all_files: Set[str]) -> Set[str]:
        resolved: Set[str] = set()
        if resource_str.startswith(('http:', 'https:', '//', 'data:')): # Ignora URLs externas/data URIs
            return resolved

        norm_html = self.normalize_path(resource_str, current_dir)
        if norm_html and norm_html in all_files:
            resolved.add(norm_html)
        elif '.' not in os.path.basename(resource_str): # Se não houver extensão, tenta adicionar comuns
            common_exts_html = ['.js', '.css', '.html', '.png', '.jpg', '.svg']
            for ext_add_html in common_exts_html:
                norm_ext_html = self.normalize_path(resource_str + ext_add_html, current_dir)
                if norm_ext_html and norm_ext_html in all_files:
                    resolved.add(norm_ext_html)
                    break
        return resolved

# --- Analisadores AST Específicos por Linguagem ---
class ASTPythonAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.imports: Set[str] = set()
    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.add(alias.name)
        self.generic_visit(node)
    def visit_ImportFrom(self, node: ast.ImportFrom):
        module_name = node.module
        if node.level > 0: # Import relativo
            prefix = '.' * node.level
            full_name = prefix + module_name if module_name else prefix
            self.imports.add(full_name)
        elif module_name: # Import absoluto
            self.imports.add(module_name)
        self.generic_visit(node)
    def visit_Call(self, node: ast.Call): # Suporte para __import__ e importlib.import_module
        if isinstance(node.func, ast.Name) and node.func.id == '__import__' and \
           node.args and isinstance(node.args[0], (ast.Str, ast.Constant) ): # ast.Str para Python < 3.8
            val = node.args[0].s if isinstance(node.args[0], ast.Str) else node.args[0].value
            if isinstance(val, str): self.imports.add(val)
        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and \
             node.func.value.id == 'importlib' and node.func.attr == 'import_module' and \
             node.args and isinstance(node.args[0], (ast.Str, ast.Constant) ):
            val = node.args[0].s if isinstance(node.args[0], ast.Str) else node.args[0].value
            if isinstance(val, str): self.imports.add(val)
        self.generic_visit(node)

def analyze_dependencies_python_ast(fp: str, ct: str, an: RobustDependencyAnalyzer, afs: Set[str]) -> Set[str]:
    deps: Set[str] = set()
    cd = os.path.dirname(fp) if os.path.dirname(fp) else "" # Diretório atual do arquivo
    try:
        tree = ast.parse(ct, filename=fp)
        visitor = ASTPythonAnalyzer()
        visitor.visit(tree)
        for imp_s in visitor.imports:
            rps = an.resolve_import_with_fallbacks(imp_s, 'python_module', cd, afs)
            for rpi in rps:
                if rpi != fp: deps.add(rpi) # Evita auto-dependência
    except SyntaxError as e_s:
        an.progress_callback(f"WARN: Python AST SyntaxError {fp}: {e_s}")
    except Exception as e_g:
        an.progress_callback(f"ERROR: Python AST analysis failure for {fp}: {e_g}")
    return deps

def extract_js_imports_from_ast_node(node) -> Set[str]: # Helper para JS AST
    imps: Set[str] = set()
    if isinstance(node, dict):
        node_type = node.get('type')
        source_value = None
        if node_type == 'ImportDeclaration' and node.get('source') and isinstance(node['source'].get('value'), str):
            source_value = node['source']['value']
        elif node_type == 'ExportNamedDeclaration' and node.get('source') and isinstance(node['source'].get('value'), str):
            source_value = node['source']['value']
        elif node_type == 'ExportAllDeclaration' and node.get('source') and isinstance(node['source'].get('value'), str):
            source_value = node['source']['value']
        elif node_type == 'CallExpression':
            callee = node.get('callee', {})
            is_require = callee.get('type') == 'Identifier' and callee.get('name') == 'require'
            is_dynamic_import = callee.get('type') == 'Import' # Para import()
            if is_require or is_dynamic_import:
                args = node.get('arguments', [])
                if args and len(args) > 0 and isinstance(args[0], dict) and \
                   args[0].get('type') == 'Literal' and isinstance(args[0].get('value'), str):
                    source_value = args[0]['value']
        if source_value:
            imps.add(source_value)
        for v_item in node.values(): # Recursivamente varre o nó AST
            imps.update(extract_js_imports_from_ast_node(v_item))
    elif isinstance(node, list):
        for l_item in node: # Recursivamente varre listas no AST
            imps.update(extract_js_imports_from_ast_node(l_item))
    return imps

def analyze_dependencies_js_ast(fp: str, ct: str, an: RobustDependencyAnalyzer, afs: Set[str]) -> Set[str]:
    if not PYJSPARSER_AVAILABLE:
        return set()
    deps: Set[str] = set()
    cd = os.path.dirname(fp) if os.path.dirname(fp) else ""
    try:
        ast_tree_js = pyjsparser.parse(ct)
        raw_imports_js = extract_js_imports_from_ast_node(ast_tree_js)
        resolver_type_js = 'relative_path_ts' if fp.lower().endswith(('.ts', '.tsx')) else 'relative_path_js'
        for import_str_js in raw_imports_js:
            resolved_paths_js = an.resolve_import_with_fallbacks(import_str_js, resolver_type_js, cd, afs)
            for rp_item_js in resolved_paths_js:
                if rp_item_js != fp: deps.add(rp_item_js)
    except Exception as e_j: # pyjsparser. común PyJsParserSyntaxError
        an.progress_callback(f"WARN: JS/TS AST Parser error for {fp}: {e_j}")
    return deps

def analyze_dependencies_c_cpp_ast(fp: str, ct: str, an: RobustDependencyAnalyzer, afs: Set[str]) -> Set[str]:
    if not LIBCLANG_AVAILABLE:
        return set()
    deps: Set[str] = set()
    current_dir_c = os.path.dirname(fp) if os.path.dirname(fp) else ""
    code_file_abs_c = os.path.join(an.project_root, fp)
    # Determina se é C ou C++ para flags do clang
    lang_option_c = '-x c++' if fp.lower().endswith(('.cpp', '.cxx', '.hpp', '.hxx')) else '-x c'
    # Argumentos para clang: incluir diretório do arquivo e raiz do projeto
    clang_args_c = [f'-I{os.path.dirname(code_file_abs_c)}', f'-I{an.project_root}', lang_option_c]
    try:
        idx_c = cindex.Index.create()
        # Parse o arquivo, pulando corpos de função para velocidade
        tu_c = idx_c.parse(code_file_abs_c, args=clang_args_c,
                           options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD | \
                                   cindex.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES)
        for child_node_c in tu_c.cursor.get_children():
            if child_node_c.kind == cindex.CursorKind.INCLUSION_DIRECTIVE:
                included_file_raw_c = child_node_c.displayname # Nome como aparece no #include
                resolved_clang_path_c = None
                try: # Tenta obter o caminho absoluto do arquivo incluído pelo clang
                    if child_node_c.get_included_file() and child_node_c.get_included_file().name.startswith(an.project_root):
                        resolved_clang_path_c = os.path.relpath(child_node_c.get_included_file().name, an.project_root).replace('\\', '/')
                except Exception: pass # Pode falhar se o arquivo não for encontrado por clang

                if resolved_clang_path_c and resolved_clang_path_c in afs and resolved_clang_path_c != fp:
                    deps.add(resolved_clang_path_c)
                else: # Fallback para resolvedor manual se clang não fornecer caminho no projeto
                    resolved_manual_c = an.resolve_import_with_fallbacks(included_file_raw_c, 'relative_path_c', current_dir_c, afs)
                    for rp_c_item in resolved_manual_c:
                        if rp_c_item != fp: deps.add(rp_c_item)
    except cindex.LibclangError as e_clg:
        an.progress_callback(f"ERROR: Libclang error for {fp}: {e_clg}")
    except Exception as e_c_g:
        an.progress_callback(f"ERROR: C/C++ AST analysis failure for {fp}: {e_c_g}")
    return deps

def analyze_dependencies_html_ast(fp: str, ct: str, an: RobustDependencyAnalyzer, afs: Set[str]) -> Set[str]:
    if not BEAUTIFULSOUP_AVAILABLE:
        return set()
    deps: Set[str] = set()
    cd_h = os.path.dirname(fp) if os.path.dirname(fp) else ""
    try:
        soup_h = BeautifulSoup(ct, 'lxml') # 'lxml' é rápido; 'html.parser' é built-in mas mais lento
        # Tags e atributos comuns que referenciam outros arquivos
        tags_attrs_h = [('script', 'src'), ('link', 'href'), ('img', 'src'), ('source', 'src'), ('a', 'href')] # Adicionado img, source, a
        for tag_name_h, attr_name_h in tags_attrs_h:
            for node_h in soup_h.find_all(tag_name_h):
                resource_val_h = node_h.get(attr_name_h)
                if isinstance(resource_val_h, str) and resource_val_h.strip():
                    # Para <link>, considera apenas stylesheets; para <a>, apenas caminhos relativos
                    if tag_name_h == 'link' and not ('stylesheet' in (node_h.get('rel') or [])):
                        continue
                    if tag_name_h == 'a' and (resource_val_h.startswith('#') or ':' in resource_val_h): # Ignora âncoras e URLs absolutas
                        continue

                    resolved_paths_h = an.resolve_import_with_fallbacks(resource_val_h, 'relative_path_html_resource', cd_h, afs)
                    for rp_h_item in resolved_paths_h:
                        if rp_h_item != fp: deps.add(rp_h_item)
    except Exception as e_h:
        an.progress_callback(f"ERROR: HTML analysis failure for {fp}: {e_h}")
    return deps

# Mapeamento de extensões de arquivo para suas respectivas funções de análise AST
AST_PARSERS_MAP: Dict[str, Callable] = {
    '.py': analyze_dependencies_python_ast, '.pyw': analyze_dependencies_python_ast,
    '.js': analyze_dependencies_js_ast, '.jsx': analyze_dependencies_js_ast,
    '.ts': analyze_dependencies_js_ast, '.tsx': analyze_dependencies_js_ast, # Usa o mesmo parser de JS
    '.c': analyze_dependencies_c_cpp_ast, '.cpp': analyze_dependencies_c_cpp_ast, '.cxx': analyze_dependencies_c_cpp_ast,
    '.h': analyze_dependencies_c_cpp_ast, '.hpp': analyze_dependencies_c_cpp_ast, '.hxx': analyze_dependencies_c_cpp_ast,
    '.html': analyze_dependencies_html_ast, '.htm': analyze_dependencies_html_ast,
}

def _analyze_single_file_deps_task(file_info: FileInfo, analyzer: RobustDependencyAnalyzer, all_project_files_set: Set[str]) -> Tuple[str, Set[str], str, Optional[str]]:
    # Verifica o cache primeiro
    if file_info.path in analyzer.cache._cache:
        deps_c = analyzer.cache.get(file_info.path)
        return file_info.path, deps_c if deps_c is not None else set(), "success (cached)", None

    parser_func = AST_PARSERS_MAP.get(file_info.ext)
    if parser_func:
        analyzer.file_stats[f"ast_{file_info.ext}"] += 1
        deps_f = parser_func(file_info.path, file_info.original_content, analyzer, all_project_files_set)
        analyzer.cache.set(file_info.path, deps_f)
        return file_info.path, deps_f, "success", None
    else:
        # Se não houver parser AST, as dependências não são analisadas para este arquivo
        analyzer.file_stats[f"skipped_dep_analysis_{file_info.ext}"] += 1
        analyzer.cache.set(file_info.path, set()) # Cache como vazio para evitar reprocessamento
        return file_info.path, set(), "skipped (no AST parser)", None

def get_transitive_dependencies_for_file(target_fp: str, all_finfo_map: Dict[str, FileInfo],
                                       analyzer: RobustDependencyAnalyzer, all_proj_files_set: Set[str],
                                       max_depth: int = 20) -> Set[str]:
    memo_transitive: Dict[str, Set[str]] = {} # Memoization para evitar recomputar dependências transitivas

    def _recursive_get_trans(current_fp: str, visited_paths: Set[str], current_depth: int) -> Set[str]:
        if current_fp in visited_paths or current_depth > max_depth: # Evita ciclos e profundidade excessiva
            return set()
        if current_fp in memo_transitive: # Retorna do cache se já calculado
            return memo_transitive[current_fp]

        visited_paths.add(current_fp)
        file_info_obj = all_finfo_map.get(current_fp)
        if not file_info_obj:
            memo_transitive[current_fp] = set()
            return set()

        # Garante que as dependências diretas foram analisadas
        if file_info_obj.direct_dependencies is None or file_info_obj.dependency_analysis_status == "pending":
            _path, direct_deps, status, err_msg = _analyze_single_file_deps_task(file_info_obj, analyzer, all_proj_files_set)
            file_info_obj.direct_dependencies = direct_deps
            file_info_obj.dependency_analysis_status = status
            file_info_obj.dependency_analysis_error = err_msg

        current_transitive_deps = set(file_info_obj.direct_dependencies)
        for dep_path_item in file_info_obj.direct_dependencies:
            if dep_path_item in all_finfo_map: # Apenas considera dependências dentro do projeto mapeado
                current_transitive_deps.update(_recursive_get_trans(dep_path_item, visited_paths.copy(), current_depth + 1))

        memo_transitive[current_fp] = current_transitive_deps
        return current_transitive_deps

    all_transitive_deps_val = _recursive_get_trans(target_fp, set(), 0)
    target_file_info_obj = all_finfo_map.get(target_fp)
    if target_file_info_obj: # Armazena o resultado no objeto FileInfo
        target_file_info_obj.transitive_dependencies = all_transitive_deps_val
    return all_transitive_deps_val

def get_project_structure_display(src_dir_abs: str, rel_file_paths: List[str]) -> str: # src_dir_abs não é usado aqui, mas mantido por compatibilidade se necessário
    if not rel_file_paths:
        return "No relevant files found in the project."
    structure_lines = ["Project Structure:", ""]
    tree_root: Dict = {} # Dicionário aninhado para representar a árvore de diretórios

    for rel_path_str_val in sorted(list(set(rel_file_paths))): # Ordena para consistência
        path_obj_val = Path(rel_path_str_val)
        current_level_dict_val = tree_root
        for part_name_val in path_obj_val.parts:
            current_level_dict_val = current_level_dict_val.setdefault(part_name_val, {})

    def _generate_tree_lines_recursive(current_node_dict_val: dict, current_prefix_val: str = "") -> List[str]:
        output_lines_val: List[str] = []
        # Ordena itens: diretórios primeiro (aqueles com sub-dicionários não vazios), depois arquivos, alfabeticamente
        sorted_item_names_val = sorted(current_node_dict_val.keys(),
                                     key=lambda k_val: (not bool(current_node_dict_val[k_val]), k_val))
        for i_val, item_name_str_val in enumerate(sorted_item_names_val):
            is_last_item_val = (i_val == len(sorted_item_names_val) - 1)
            connector_char_val = "└── " if is_last_item_val else "├── "
            output_lines_val.append(f"{current_prefix_val}{connector_char_val}{item_name_str_val}")
            if current_node_dict_val[item_name_str_val]: # Se for um diretório (tem filhos)
                new_prefix_extension_val = "    " if is_last_item_val else "│   "
                output_lines_val.extend(_generate_tree_lines_recursive(current_node_dict_val[item_name_str_val],
                                                                    current_prefix_val + new_prefix_extension_val))
        return output_lines_val

    structure_lines.extend(_generate_tree_lines_recursive(tree_root))
    return "\n".join(structure_lines)

MAX_THREADS = os.cpu_count() or 4 # Define o número máximo de threads para pools

def process_project_folder(source_dir: str, dest_dir: str,
                           selected_lang_extensions_ui: Set[str],
                           progress_callback_ui: Callable[[str], str]
                           ) -> Tuple[List[str], int]:
    logs_list: List[str] = []
    txt_count: int = 0
    processed_ext_stats = Counter() # Estatísticas de arquivos processados por extensão
    skipped_ext_stats = Counter()   # Estatísticas de arquivos ignorados ou não selecionados

    def _log_ui(msg: str, is_err: bool = False) -> str: # is_err não usado, mas mantido por compatibilidade
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S') # Movido para dentro para timestamp mais preciso
        logs_list.append(f"[{timestamp}] {msg}")
        progress_callback_ui(msg) # Envia mensagem para a UI
        return timestamp # Retorna o timestamp para uso na escrita de arquivos

    _log_ui(f"INFO: Processing project: {source_dir}")
    analyzer_instance = RobustDependencyAnalyzer(project_root=source_dir, progress_callback=lambda m: _log_ui(f"ANALYZER: {m}"))
    analyzer_instance.cache.clear()

    all_files_map: Dict[str, FileInfo] = {} # Mapeia caminhos relativos para objetos FileInfo
    project_scan_rel_paths: List[str] = [] # Lista de caminhos relativos para a estrutura do projeto

    _log_ui("INFO: Scanning project files...")
    for root_path, sub_dirs, files_in_dir in os.walk(source_dir, topdown=True):
        # Filtra diretórios ignorados
        sub_dirs[:] = [d_name for d_name in sub_dirs if d_name not in IGNORED_ITEMS and
                       not any(fnmatch(d_name, pattern_item) for pattern_item in IGNORED_ITEMS if '*' in pattern_item or '?' in pattern_item)]
        for file_name_item in files_in_dir:
            # Filtra arquivos ignorados
            if file_name_item in IGNORED_ITEMS or \
               any(fnmatch(file_name_item, pattern_item) for pattern_item in IGNORED_ITEMS if '*' in pattern_item or '?' in pattern_item):
                skipped_ext_stats['ignored_item'] += 1
                continue

            file_abs_path = os.path.join(root_path, file_name_item)
            rel_file_path = os.path.relpath(file_abs_path, source_dir).replace('\\', '/')
            _file_name_part_val, file_ext_val = os.path.splitext(file_name_item)
            file_ext_lower_val = file_ext_val.lower()

            # Processa apenas se a extensão for suportada E selecionada na UI
            if file_ext_lower_val in ALL_EFFECTIVELY_SUPPORTED_EXTENSIONS and file_ext_lower_val in selected_lang_extensions_ui:
                project_scan_rel_paths.append(rel_file_path)
                processed_ext_stats[file_ext_lower_val] += 1
                try:
                    with open(file_abs_path, 'r', encoding='utf-8', errors='ignore') as f_in_handle:
                        original_content_val = f_in_handle.read()
                    cleaned_content_val = analyzer_instance.clean_code_content(original_content_val, file_ext_lower_val)
                    file_stats_info = os.stat(file_abs_path)
                    all_files_map[rel_file_path] = FileInfo(
                        path=rel_file_path, content=cleaned_content_val, original_content=original_content_val,
                        original_name=file_name_item, ext=file_ext_lower_val,
                        size=file_stats_info.st_size, last_modified=file_stats_info.st_mtime
                    )
                except Exception as e_read_file:
                    _log_ui(f"ERROR: Failed to read/process file {rel_file_path}: {e_read_file}", is_err=True)
            elif file_ext_lower_val in selected_lang_extensions_ui: # Selecionado, mas não suportado robustamente
                skipped_ext_stats[f"{file_ext_lower_val} (selected_but_not_robust)"] +=1
            else: # Não selecionado ou não suportado
                skipped_ext_stats[file_ext_lower_val] +=1

    if not all_files_map:
        _log_ui("WARN: No files matching supported and selected extensions found for processing.")
        return logs_list, 0

    _log_ui(f"INFO: {len(all_files_map)} files identified for robust processing. Analyzing direct dependencies...")
    all_project_files_set = set(all_files_map.keys())

    # Análise de dependências diretas em paralelo
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor_direct:
        future_to_path_direct = {
            executor_direct.submit(_analyze_single_file_deps_task, finfo_obj, analyzer_instance, all_project_files_set): fp_key
            for fp_key, finfo_obj in all_files_map.items()
        }
        for i_direct_dep, future_direct_dep in enumerate(as_completed(future_to_path_direct)):
            file_path_direct_dep = future_to_path_direct[future_direct_dep]
            try:
                _path_res, direct_deps_res, status_res, err_msg_res = future_direct_dep.result()
                all_files_map[file_path_direct_dep].direct_dependencies = direct_deps_res
                all_files_map[file_path_direct_dep].dependency_analysis_status = status_res
                all_files_map[file_path_direct_dep].dependency_analysis_error = err_msg_res
            except Exception as e_direct_task_err:
                _log_ui(f"ERROR: Task for direct deps of {file_path_direct_dep} failed: {e_direct_task_err}", is_err=True)
                all_files_map[file_path_direct_dep].dependency_analysis_status = "error (task_direct_fatal)"
                all_files_map[file_path_direct_dep].dependency_analysis_error = str(e_direct_task_err)
            if (i_direct_dep + 1) % (len(all_files_map) // 20 or 1) == 0: # Log de progresso
                 _log_ui(f"INFO: Direct dependencies analyzed for {i_direct_dep+1}/{len(all_files_map)} files.")

    _log_ui("INFO: Direct dependency analysis complete. Calculating transitive dependencies...")
    # Análise de dependências transitivas em paralelo
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor_transitive:
        future_to_path_transitive = {
            executor_transitive.submit(get_transitive_dependencies_for_file,
                           fp_key_trans, all_files_map, analyzer_instance, all_project_files_set): fp_key_trans
            for fp_key_trans in all_files_map.keys()
        }
        for i_trans_dep, future_trans_dep in enumerate(as_completed(future_to_path_transitive)):
            file_path_trans_dep = future_to_path_transitive[future_trans_dep]
            try:
                _ = future_trans_dep.result() # A função get_transitive_dependencies_for_file modifica all_files_map
            except Exception as e_trans_task_err:
                 _log_ui(f"ERROR: Task for transitive deps of {file_path_trans_dep} failed: {e_trans_task_err}", is_err=True)
                 if file_path_trans_dep in all_files_map:
                     all_files_map[file_path_trans_dep].dependency_analysis_status += " (transitive_task_fatal)"
            if (i_trans_dep + 1) % (len(all_files_map) // 20 or 1) == 0: # Log de progresso
                _log_ui(f"INFO: Transitive dependencies calculated for {i_trans_dep+1}/{len(all_files_map)} files.")

    _log_ui("INFO: Full dependency analysis complete.")
    for stat_key, stat_count in analyzer_instance.file_stats.items():
        _log_ui(f"STATS: Analyzer {stat_key} used {stat_count} times.")

    project_structure_str = get_project_structure_display(analyzer_instance.project_root, project_scan_rel_paths)
    _log_ui("INFO: Generating context output files...")
    os.makedirs(dest_dir, exist_ok=True)

    # Gera o arquivo de visão geral do projeto
    main_overview_filename = "_PROJECT_OVERVIEW_CONTEXT.txt"
    main_overview_filepath = os.path.join(dest_dir, main_overview_filename)
    try:
        with open(main_overview_filepath, 'w', encoding='utf-8') as f_out_main:
            ts_main = _log_ui("") # Obtém timestamp atual para o arquivo
            f_out_main.write(f"AI CONTEXT - PROJECT OVERVIEW\n")
            f_out_main.write(f"Project Root: {analyzer_instance.project_root}\nGenerated at: {ts_main}\n")
            f_out_main.write("=" * 80 + "\n")
            f_out_main.write(project_structure_str + "\n\n")
            f_out_main.write("=" * 80 + "\n")
            f_out_main.write("ALL PROCESSED SOURCE FILES IN PROJECT:\n")
            f_out_main.write("=" * 80 + "\n")
            for path_str_sorted in sorted(project_scan_rel_paths):
                f_out_main.write(f"- {path_str_sorted}\n")
            f_out_main.write("\n")
        _log_ui(f"SUCCESS: Main project overview file generated: {main_overview_filename}")
        txt_count += 1
    except Exception as e_main_out:
        _log_ui(f"ERROR: Failed to generate main overview file {main_overview_filepath}: {e_main_out}", is_err=True)

    # Gera arquivos de contexto individuais para cada arquivo processado
    for i_out_file_idx, (rel_path_key, file_info_data_obj) in enumerate(all_files_map.items()):
        output_base_name = file_info_data_obj.original_name
        output_txt_name = f"{output_base_name}.txt"
        file_dir_relative = os.path.dirname(rel_path_key)
        output_file_dir_path = os.path.join(dest_dir, file_dir_relative)
        os.makedirs(output_file_dir_path, exist_ok=True)
        output_file_filepath = os.path.join(output_file_dir_path, output_txt_name)
        try:
            with open(output_file_filepath, 'w', encoding='utf-8') as f_out_individual:
                ts_individual = _log_ui("") # Timestamp para este arquivo
                f_out_individual.write(f"AI CONTEXT - Source File Focus: {file_info_data_obj.path}\n")
                f_out_individual.write(f"Project Root: {analyzer_instance.project_root}\nGenerated at: {ts_individual}\n")
                f_out_individual.write("=" * 80 + "\n")
                f_out_individual.write(project_structure_str + "\n\n") # Inclui estrutura em cada arquivo
                f_out_individual.write("=" * 80 + "\n")
                f_out_individual.write(f"FOCUSED FILE CONTENT: {file_info_data_obj.path}\n")
                f_out_individual.write(f"(Dependency Analysis Status: {file_info_data_obj.dependency_analysis_status})\n")
                if file_info_data_obj.dependency_analysis_error:
                    f_out_individual.write(f"(Analysis Error: {file_info_data_obj.dependency_analysis_error})\n")
                f_out_individual.write("=" * 80 + "\n")
                f_out_individual.write(file_info_data_obj.content + "\n\n")

                # Inclui conteúdo de arquivos dependentes
                dependencies_to_include = file_info_data_obj.transitive_dependencies or set()
                if dependencies_to_include:
                    f_out_individual.write("=" * 80 + "\n")
                    f_out_individual.write("DEPENDENT FILES' CONTENT (intra-project):\n")
                    f_out_individual.write("=" * 80 + "\n\n")
                    for dep_path_str in sorted(list(dependencies_to_include)):
                        if dep_path_str in all_files_map: # Apenas se a dependência foi processada
                            dep_file_info_obj = all_files_map[dep_path_str]
                            f_out_individual.write(f"--- FILE (Dependency): {dep_file_info_obj.path} ---\n")
                            f_out_individual.write(dep_file_info_obj.content + "\n\n")
                else:
                    f_out_individual.write("=" * 80 + "\n")
                    f_out_individual.write("No intra-project file dependencies identified or analysis skipped/error.\n")
                    f_out_individual.write("=" * 80 + "\n\n")
            if (i_out_file_idx + 1) % (len(all_files_map) // 10 or 1) == 0: # Log de progresso
                 _log_ui(f"SUCCESS: Generated {i_out_file_idx + 1}/{len(all_files_map)} individual context files.")
            txt_count += 1
        except Exception as e_individual_out:
            _log_ui(f"ERROR: Failed to generate context file {output_file_filepath}: {e_individual_out}", is_err=True)

    # Sumário final do processamento de arquivos
    _log_ui("--- FILE PROCESSING SUMMARY ---")
    if processed_ext_stats:
        _log_ui("Files Processed (by extension):")
        for ext_proc, count_proc in processed_ext_stats.items():
            _log_ui(f"  - {ext_proc}: {count_proc} file(s)")
    else:
        _log_ui("No files were processed based on selection and support.")

    if skipped_ext_stats:
        _log_ui("Files Skipped or Ignored (by extension/reason):")
        for ext_skip, count_skip in skipped_ext_stats.items():
            _log_ui(f"  - {ext_skip}: {count_skip} file(s)")

    _log_ui(f"INFO: Processing complete. Total {txt_count} TXT files generated.")
    return logs_list, txt_count