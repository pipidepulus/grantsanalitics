"""
Script para vectorizar PDFs y cargarlos en ChromaDB.
Usa embeddings locales mediante sentence-transformers (no requiere API externa).
"""
import sys
import os
from pathlib import Path

# Agregar el directorio del proyecto al path
sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Configuración
PROJECT_DIR = Path("/home/usuario/proyectos/grantsanalitics")
PDF_SOURCE_DIR = PROJECT_DIR / "pdf_source"
VECTOR_DB_DIR = PROJECT_DIR / "vector_db"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Parámetros de chunking
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100

class PDFVectorizer:
    def __init__(self):
        """Inicializa el modelo de embeddings y la conexión con ChromaDB."""
        print(f"🔧 Cargando modelo de embeddings: {EMBEDDING_MODEL} (local)...")
        self.embedding_model = SentenceTransformer(EMBEDDING_MODEL)
        
        VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(VECTOR_DB_DIR))
        
        # Usar el embedding function nativo de chromadb
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        self.embedding_function = SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
        
        self.collection = self.client.get_or_create_collection(
            name="grants_knowledge_base",
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine"}
        )
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extrae todo el texto de un PDF."""
        try:
            reader = PdfReader(str(pdf_path))
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n\n"
            return text
        except Exception as e:
            print(f"  ❌ Error al leer {pdf_path.name}: {e}")
            return ""

    def chunk_text(self, text: str, source_name: str) -> list:
        """Divide el texto en chunkes y retorna documentos con metadatos."""
        chunks = self.text_splitter.split_text(text)
        documents = []
        for i, chunk in enumerate(chunks):
            documents.append({
                "id": f"{source_name}_{i}",
                "text": chunk,
                "metadata": {"source": source_name, "chunk_index": i}
            })
        return documents

    def ingest_pdf(self, pdf_path: Path) -> int:
        """Vectoriza un PDF y lo agrega a ChromaDB."""
        print(f"  📄 Procesando: {pdf_path.name}")
        
        # Extraer texto
        text = self.extract_text_from_pdf(pdf_path)
        if not text.strip():
            print(f"  ⚠️  No se pudo extraer texto de {pdf_path.name}")
            return 0
        
        # Dividir en chunkes
        documents = self.chunk_text(text, pdf_path.stem)
        
        if not documents:
            return 0
        
        # Agregar a ChromaDB
        ids = [doc["id"] for doc in documents]
        texts = [doc["text"] for doc in documents]
        metadatas = [doc["metadata"] for doc in documents]
        
        self.collection.add(
            ids=ids,
            documents=texts,
            metadatas=metadatas
        )
        
        print(f"  ✅ {pdf_path.name}: {len(documents)} chunkes vectorizados")
        return len(documents)

    def ingest_all_pdfs(self):
        """Vectoriza todos los PDFs en el directorio pdf_source/."""
        if not PDF_SOURCE_DIR.exists():
            print(f"❌ Error: El directorio {PDF_SOURCE_DIR} no existe.")
            return
        
        pdf_files = list(PDF_SOURCE_DIR.glob("*.pdf"))
        if not pdf_files:
            print(f"❌ No se encontraron archivos PDF en {PDF_SOURCE_DIR}")
            return
        
        print(f"\n📚 Encontrados {len(pdf_files)} archivos PDF:")
        for pdf in pdf_files:
            size_mb = pdf.stat().st_size / (1024 * 1024)
            print(f"   - {pdf.name} ({size_mb:.2f} MB)")
        
        print(f"\n{'='*60}")
        print("🚀 Iniciando vectorización...")
        print('='*60)
        
        total_chunks = 0
        results = {}
        
        for pdf_file in pdf_files:
            count = self.ingest_pdf(pdf_file)
            results[pdf_file.name] = count
            total_chunks += count
        
        # Resumen
        print(f"\n{'='*60}")
        print("📊 Resumen de Ingestión")
        print('='*60)
        for file, count in results.items():
            status = "✅" if count > 0 else "⚠️"
            print(f"  {status} {file}: {count} chunkes")
        
        print(f"\n📈 Total de chunkes en ChromaDB: {total_chunks}")
        print(f"📂 Base de datos en: {VECTOR_DB_DIR}")
        print("="*60)
        print("✅ Vectorización completada.")
        
        return results

    def query(self, query_text: str, n_results: int = 5):
        """Realiza una búsqueda semántica."""
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            include=["documents", "metadatas", "distances"]
        )
        
        formatted_results = []
        for i, doc in enumerate(results['documents'][0]):
            formatted_results.append({
                "document": doc,
                "metadata": results['metadatas'][0][i],
                "distance": results['distances'][0][i]
            })
        return formatted_results

    def get_stats(self):
        """Retorna estadísticas de la base de datos."""
        return {
            "total_chunks": self.collection.count(),
            "db_path": str(VECTOR_DB_DIR)
        }


if __name__ == "__main__":
    print("=" * 60)
    print("  Pipidepulus AI - Vectorizador de PDFs (100% Local)")
    print("=" * 60)
    print()
    
    vectorizer = PDFVectorizer()
    results = vectorizer.ingest_all_pdfs()
    
    # Prueba de consulta
    print(f"\n{'='*60}")
    print("🔍 Verificación - Estado de la base de datos")
    print('='*60)
    print(f"Total de chunkes: {vectorizer.get_stats()['total_chunks']}")
    
    print(f"\n{'='*60}")
    print("✅ Proceso completado. La base de datos está lista.")
    print("=" * 60)
