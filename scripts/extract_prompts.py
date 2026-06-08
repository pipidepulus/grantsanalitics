import chromadb
from pathlib import Path
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
import re
import json

DB_PATH = Path("/home/usuario/proyectos/grantsanalitics/vector_db")
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Patrones para identificar prompts técnicos
PROMPT_PATTERNS = [
    r"(?i)^Quiero que actúes como",
    r"(?i)^Actúa como",
    r"(?i)^Eres un experto",
    r"(?i)^Quiero que elabores",
    r"(?i)^Quiero que analices",
    r"(?i)^Prompt",
    r"(?i)^Descripción:",
]

def identify_prompts():
    """Identifica y extrae los prompts técnicos de la base de datos."""
    print("🔍 Identificando prompts técnicos en la base de datos...")
    
    client = chromadb.PersistentClient(path=str(DB_PATH))
    embedding_func = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
    collection = client.get_collection(name="grants_knowledge_base", embedding_function=embedding_func)
    
    all_ids = collection.get(include=[])['ids']
    all_data = collection.get(include=['documents', 'metadatas'])
    
    prompts = []
    
    for i, chunk_id in enumerate(all_ids):
        text = all_data['documents'][i]
        metadata = all_data['metadatas'][i]
        source = metadata.get('source', 'Unknown')
        
        # Verificar si el texto coincide con patrones de prompt
        is_prompt = False
        for pattern in PROMPT_PATTERNS:
            if re.search(pattern, text):
                is_prompt = True
                break
        
        if is_prompt:
            # Limpiar el prompt: eliminar saltos de línea innecesarios y espacios extra
            clean_text = re.sub(r'\s+', ' ', text).strip()
            
            # Intentar categorizar el prompt basándose en el contenido o fuente
            category = "General"
            text_lower = clean_text.lower()
            
            if any(kw in text_lower for kw in ["árbol de problemas", "causas", "efectos"]):
                category = "Crea: Definición del Problema"
            elif any(kw in text_lower for kw in ["cadena de valor", "objetivos específicos", "productos"]):
                category = "Crea: Cadena de Valor"
            elif any(kw in text_lower for kw in ["estrategia", "matriz eric", "oceano azul"]):
                category = "Crea: Estrategia e Innovación"
            elif any(kw in text_lower for kw in ["metodología", "actividades", "cronograma"]):
                category = "Desarrolla: Metodología y Cronograma"
            elif any(kw in text_lower for kw in ["presupuesto", "rubros", "costos"]):
                category = "Desarrolla: Presupuesto"
            elif any(kw in text_lower for kw in ["validador", "evaluación", "criterios"]):
                category = "Valida: Evaluación"
            elif any(kw in text_lower for kw in ["réplica", "adaptar", "convocatoria"]):
                category = "Réplica: Adaptación"
            elif any(kw in text_lower for kw in ["aliados", "alianzas", "fronting"]):
                category = "Desarrolla: Aliados"
            elif any(kw in text_lower for kw in ["beneficiario", "avatar", "usuario ideal"]):
                category = "Detecta: Beneficiario"
            elif any(kw in text_lower for kw in ["convocatorias", "detecta convocatorias"]):
                category = "Detecta: Convocatorias"
            else:
                category = "General: Prompt de Estructuración"
                
            prompts.append({
                "category": category,
                "source": source,
                "prompt": clean_text
            })
            
    print(f"✅ Se identificaron {len(prompts)} prompts técnicos.")
    return prompts

def save_prompts_to_file(prompts):
    """Guarda los prompts en un archivo JSON estructurado."""
    output_file = Path("/home/usuario/proyectos/grantsanalitics/backend/core/system_prompts.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(prompts, f, ensure_ascii=False, indent=2)
        
    print(f"📁 Prompts guardados en: {output_file}")

if __name__ == "__main__":
    print("=" * 60)
    print("  Pipidepulus AI - Extractor de Prompts Técnicos")
    print("=" * 60)
    
    prompts = identify_prompts()
    if prompts:
        save_prompts_to_file(prompts)
    else:
        print("⚠️ No se encontraron prompts técnicos.")
