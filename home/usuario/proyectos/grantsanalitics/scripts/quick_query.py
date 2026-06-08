import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

DB_PATH = Path("/home/usuario/proyectos/grantsanalitics/vector_db")
client = chromadb.PersistentClient(path=str(DB_PATH))
embedding_func = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
collection = client.get_collection(name="grants_knowledge_base", embedding_function=embedding_func)

print("🔍 Modo de Consulta Rápida (Escribe 'salir' para terminar)")
print("="*60)

while True:
    query = input("\n¿Qué quieres saber? > ").strip()
    if query.lower() in ['salir', 'exit', 'q']:
        break
    
    if not query:
        continue
    
    results = collection.query(
        query_texts=[query],
        n_results=3,
        include=["documents", "metadatas", "distances"]
    )
    
    print("\n--- Resultados ---")
    for i, doc in enumerate(results['documents'][0]):
        distance = results['distances'][0][i]
        source = results['metadatas'][0][i].get('source', 'Desconocido')
        print(f"\n📄 Fuente: {source} (Similitud: {1 - distance:.2%})")
        print(f"Texto: {doc[:300]}...")
        print("-"*60)
