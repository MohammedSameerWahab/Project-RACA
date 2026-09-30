from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
REPOSITORIES_DIR = DATA_DIR / "repositories"
INDEXES_DIR = DATA_DIR / "indexes"

COCOINDEX_DB_PATH = DATA_DIR / "cocoindex.db"
COCOINDEX_GRAPH_DB_PATH = DATA_DIR / "cocoindex_graph.db"

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

CHUNK_SIZE = 1000
MIN_CHUNK_SIZE = 300
CHUNK_OVERLAP = 300

REPOSITORIES_DIR.mkdir(parents=True, exist_ok=True)
INDEXES_DIR.mkdir(parents=True, exist_ok=True)