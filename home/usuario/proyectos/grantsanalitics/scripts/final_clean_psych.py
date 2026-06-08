import chromadb
from pathlib import Path
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

DB_PATH = Path("/home/usuario/proyectos/grantsanalitics/vector_db")
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

client = chromadb.PersistentClient(path=str(DB_PATH))
embedding_func = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
collection = client.get_collection(name="grants_knowledge_base", embedding_function=embedding_func)

# Obtenemos todos los IDs y documentos para identificar los de psicoanálisis
all_data = collection.get(include=['documents', 'metadatas'])
to_delete = []

print("🔍 Buscando chunks de 'psicoanálisis' y 'desarrollo personal'...")

for i, doc in enumerate(all_data['documents']):
    # Buscar la combinación específica que indica el prompt de psicoanálisis
    if 'psicoanálisis' in doc.lower() and 'desarrollo personal' in doc.lower():
        to_delete.append(all_data['ids'][i])
        print(f"  - Encontrado: {all_data['metadatas'][i]['source']}")

if to_delete:
    print(f"\n🗑️  Eliminando {len(to_delete)} chunks de psicoanálisis...")
    collection.delete(ids=to_delete)
    print("✅ Chunks eliminados correctamente.")
else:
    print("✅ No se encontraron más chunks de psicoanálisis.")

print(f"\n📈 Total de chunks restante: {collection.count()}")
