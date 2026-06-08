import chromadb
from pathlib import Path
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
import re

# Configuración
DB_PATH = Path("/home/usuario/proyectos/grantsanalitics/vector_db")
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Patrones de "Ruido" (Lo que queremos eliminar)
NOISE_PATTERNS = [
    # Comercial/Ventas
    r"(?i)hotmart|inscripción|precio.*USD|pago.*mensual|bono.*adicional|descuento.*temporal|oferta.*limitada",
    # Links externos/no técnicos
    r"(?i)https?://.*wa\.link|https?://.*bit\.ly|https?://.*hotmart\.com",
    # Contacto/Venta
    r"(?i)línea de soporte|copiloto|asesor.*comercial|whatsapp.*apoyo",
    # Marketing/Vaguedad
    r"(?i)más información en|visita nuestra web|síguenos en redes|suscríbete al boletín",
    # Psicoanálisis puro (sin contexto técnico de proyecto)
    r"(?i)síndrome del impostor|creencias limitantes.*personal|miedo al fracaso.*psicológico|autoconocimiento.*profundo",
]

# Palabras Clave de "Valor Técnico" (Lo que queremos proteger)
TECHNICAL_KEYWORDS = [
    # Metodología Propulsa / SDD
    "árbol de problemas", "cadena de valor", "objetivos específicos", "indicadores",
    "metas", "actividades", "presupuesto", "cronograma", "hitos", "metodología",
    "evaluación", "criterios", "coherencia", "viabilidad", "sostenibilidad",
    # Herramientas Lógicas
    "matriz eric", "matriz nodriza", "lienzo innuva", "foco estratégico",
    "beneficiario ideal", "proponente", "aliado", "convocatoria", "subvención",
    "financiamiento", "presupuesto base", "rubros", "talento humano",
    # Términos Técnicos Genéricos
    "impacto social", "población beneficiaria", "territorio", "innovación",
    "transferencia tecnológica", "riesgos", "mitigación", "entregables",
    "producto mínimo viable", "hipótesis", "validación técnica", "validación social"
]

def is_noise(text):
    """Verifica si el texto coincide con los patrones de ruido comercial/marketing."""
    for pattern in NOISE_PATTERNS:
        if re.search(pattern, text):
            return True
    return False

def has_technical_value(text):
    """Verifica si el texto contiene al menos una palabra clave técnica importante."""
    text_lower = text.lower()
    for keyword in TECHNICAL_KEYWORDS:
        if keyword in text_lower:
            return True
    return False

def get_collection_stats(collection):
    """Obtiene estadísticas básicas de la colección."""
    count = collection.count()
    all_data = collection.get(include=['metadatas'])
    return count, all_data

def clean_database():
    """
    Analiza la base de datos y elimina los chunks que son ruido comercial 
    pero que NO tienen valor técnico asociado.
    """
    print("🔍 Iniciando análisis semántico de la base de datos...")
    
    client = chromadb.PersistentClient(path=str(DB_PATH))
    embedding_func = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
    collection = client.get_collection(name="grants_knowledge_base", embedding_function=embedding_func)
    
    total_chunks = collection.count()
    print(f"📚 Total de chunks actuales: {total_chunks}")
    
    # Obtenemos todos los datos para analizarlos
    # Nota: Si la DB es muy grande, esto puede consumir memoria. Para 40-50 PDFs está bien.
    all_ids = collection.get(include=[])['ids']
    
    chunks_to_delete = []
    chunks_to_keep = []
    
    # Analizamos los metadatos y textos
    # Primero, obtengamos todos los chunks con su texto y metadatos
    all_data = collection.get(include=['documents', 'metadatas'])
    
    for i, chunk_id in enumerate(all_ids):
        text = all_data['documents'][i]
        metadata = all_data['metadatas'][i]
        source = metadata.get('source', 'Unknown')
        
        # Lógica de decisión
        is_noisy = is_noise(text)
        is_technical = has_technical_value(text)
        
        if is_noisy and not is_technical:
            # Es ruido puro (ej: "Suscríbete a hotmart por 50 USD")
            chunks_to_delete.append(chunk_id)
        else:
            # Es técnico O es texto neutro que podría ser parte de una explicación técnica
            chunks_to_keep.append(chunk_id)
            
    print(f"\n📊 Resultados del análisis:")
    print(f"  🗑️  Chunks a ELIMINAR (Ruido puro): {len(chunks_to_delete)}")
    print(f"  ✅ Chunks a MANTENER (Técnicos/Neutros): {len(chunks_to_keep)}")
    
    if chunks_to_delete:
        confirm = input("\n⚠️ ¿Estás seguro de que quieres eliminar estos chunks? (s/n): ")
        if confirm.lower() == 's':
            collection.delete(ids=chunks_to_delete)
            print("✅ Chunks eliminados correctamente.")
            
            # Verificación final
            new_count = collection.count()
            print(f"📈 Nueva cuenta de chunks: {new_count}")
            
            # Mostrar ejemplos de lo que se borró y lo que se quedó
            print("\n--- Ejemplos de CHUNKS ELIMINADOS (Ruido) ---")
            for chunk_id in chunks_to_delete[:3]: # Mostrar primeros 3
                idx = all_ids.index(chunk_id)
                print(f"  - {all_data['documents'][idx][:100]}...")
                
            print("\n--- Ejemplos de CHUNKS MANTENIDOS (Técnico) ---")
            for chunk_id in chunks_to_keep[:3]: # Mostrar primeros 3
                idx = all_ids.index(chunk_id)
                print(f"  - {all_data['documents'][idx][:100]}...")
        else:
            print("❌ Operación cancelada.")
    else:
        print("\n✅ No se encontraron chunks de ruido puro. La base de datos está limpia.")

if __name__ == "__main__":
    print("=" * 60)
    print("  Pipidepulus AI - Limpieza Semántica de Base de Datos")
    print("=" * 60)
    clean_database()
