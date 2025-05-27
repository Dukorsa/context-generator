import re

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
        (re.compile(r'"""(?:.|\n)*?"""', re.DOTALL), 0), # Captura docstrings/comentários multilinhas com aspas duplas
        (re.compile(r"'''(?:.|\n)*?'''", re.DOTALL), 0)  # Captura docstrings/comentários multilinhas com aspas simples
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
    ".h": [
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
    ".css": [(re.compile(r'/\*(?:.|\n)*?\*/', re.DOTALL), 0)],
    ".sql": [
        (re.compile(r'--.*'), 0),
        (re.compile(r'/\*(?:.|\n)*?\*/', re.DOTALL), 0)
    ],
    ".md": [], 
    ".txt": []
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