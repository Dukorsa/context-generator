# config.py
import re

# Linguagens suportadas (APENAS AS COM ANÁLISE DE DEPENDÊNCIA AST ROBUSTA)
# A UI usará esta lista.
SUPPORTED_LANGUAGES = {
    "Python": [".py", ".pyw"],
    "JavaScript": [".js", ".jsx"],
    "TypeScript": [".ts", ".tsx"], # Aproximado com parser JS, mas mantido por popularidade
    "HTML": [".html", ".htm"],
    "C++": [".cpp", ".h", ".hpp", ".cxx", ".hxx"], # Agrupando C e C++
    "C": [".c", ".h"], # Mantido separado para clareza, mas pode ser mesclado com C++
}

# Gerar um conjunto de todas as extensões efetivamente suportadas para fácil checagem
ALL_EFFECTIVELY_SUPPORTED_EXTENSIONS = set()
for lang_exts in SUPPORTED_LANGUAGES.values():
    ALL_EFFECTIVELY_SUPPORTED_EXTENSIONS.update(lang_exts)


# Padrões de Regex para remoção de comentários (mantido para as linguagens suportadas)
COMMENT_PATTERNS = {
    ".py": [
        (re.compile(r'#.*'), 0),
        (re.compile(r'"""(?:.|\n)*?"""', re.DOTALL), 0),
        (re.compile(r"'''(?:.|\n)*?'''", re.DOTALL), 0)
    ],
    ".pyw": [
        (re.compile(r'#.*'), 0),
        (re.compile(r'"""(?:.|\n)*?"""', re.DOTALL), 0),
        (re.compile(r"'''(?:.|\n)*?'''", re.DOTALL), 0)
    ],
    ".js": [
        (re.compile(r'//.*'), 0),
        (re.compile(r'/\*(?:.|\n)*?\*/', re.DOTALL), 0)
    ],
    ".jsx": [
        (re.compile(r'//.*'), 0),
        (re.compile(r'/\*(?:.|\n)*?\*/', re.DOTALL), 0),
        (re.compile(r'{/\*(?:.|\n)*?\*/}'), 0)
    ],
    ".ts": [
        (re.compile(r'//.*'), 0),
        (re.compile(r'/\*(?:.|\n)*?\*/', re.DOTALL), 0)
    ],
    ".tsx": [
        (re.compile(r'//.*'), 0),
        (re.compile(r'/\*(?:.|\n)*?\*/', re.DOTALL), 0),
        (re.compile(r'{/\*(?:.|\n)*?\*/}'), 0)
    ],
    ".html": [(re.compile(r'<!--(?:.|\n)*?-->', re.DOTALL), 0)],
    ".htm": [(re.compile(r'<!--(?:.|\n)*?-->', re.DOTALL), 0)],
    ".cpp": [
        (re.compile(r'//.*'), 0),
        (re.compile(r'/\*(?:.|\n)*?\*/', re.DOTALL), 0)
    ],
    ".h": [ # Comum para C e C++
        (re.compile(r'//.*'), 0),
        (re.compile(r'/\*(?:.|\n)*?\*/', re.DOTALL), 0)
    ],
    ".hpp": [
        (re.compile(r'//.*'), 0),
        (re.compile(r'/\*(?:.|\n)*?\*/', re.DOTALL), 0)
    ],
    ".cxx": [
        (re.compile(r'//.*'), 0),
        (re.compile(r'/\*(?:.|\n)*?\*/', re.DOTALL), 0)
    ],
    ".hxx": [
        (re.compile(r'//.*'), 0),
        (re.compile(r'/\*(?:.|\n)*?\*/', re.DOTALL), 0)
    ],
    ".c": [
        (re.compile(r'//.*'), 0),
        (re.compile(r'/\*(?:.|\n)*?\*/', re.DOTALL), 0)
    ],
    # CSS, SQL, Markdown, Text, Java, C#, Go, Ruby, PHP, Swift, Kotlin, Rust foram removidos
    # de COMMENT_PATTERNS se não estiverem mais em SUPPORTED_LANGUAGES,
    # ou mantidos se ainda forem úteis para limpeza mesmo sem análise de dependência.
    # Por simplicidade, vamos manter os padrões de comentário para CSS, SQL, MD, TXT caso
    # o usuário queira processá-los apenas para limpeza, mas eles não aparecerão na lista de linguagens
    # para seleção de dependência.
    ".css": [(re.compile(r'/\*(?:.|\n)*?\*/', re.DOTALL), 0)], # Exemplo de manutenção para limpeza
    ".sql": [ (re.compile(r'--.*'), 0), (re.compile(r'/\*(?:.|\n)*?\*/', re.DOTALL), 0)],
    ".md": [], ".txt": []
}

# Pastas e arquivos a serem ignorados universalmente (mantido)
IGNORED_ITEMS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv", "env", ".env",
    "target", "build", "dist", "out", ".vscode", ".idea", "bin", "obj",
    ".DS_Store", "*.pyc", "*.pyo", "*.log", "*.tmp", "*.bak", "*.swp",
    "*.dll", "*.exe", "*.so", "*.dylib", "*.o", "*.a", "*.lib",
    "package-lock.json", "yarn.lock", "composer.lock", "Pipfile.lock", "poetry.lock",
    "Gemfile.lock", "go.sum", "Cargo.lock",
}

# ROBUST_DEPENDENCY_SUPPORTED_EXTENSIONS não é mais necessário, usamos ALL_EFFECTIVELY_SUPPORTED_EXTENSIONS