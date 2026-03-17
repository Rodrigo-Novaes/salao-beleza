# add_config.py
import sqlite3

def init_config():
    conn = sqlite3.connect('salao.db')
    c = conn.cursor()
    
    # Inserir a configuração de tolerância se não existir
    c.execute("""
        INSERT OR IGNORE INTO configuracoes (chave, valor) 
        VALUES (?, ?)
    """, ('tolerancia_minutos', '30'))
    
    conn.commit()
    conn.close()
    print("✅ Configuração 'tolerancia_minutos' adicionada com valor 30")

if __name__ == "__main__":
    init_config()