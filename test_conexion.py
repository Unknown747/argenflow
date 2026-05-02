import MetaTrader5 as mt5
import os
from dotenv import load_dotenv

load_dotenv()

def probar_vinculacion():
    # 1. Inicializar
    if not mt5.initialize():
        print("❌ Error: No se pudo inicializar MT5. ¿Está instalado y abierto?")
        return

    # 2. Intentar Login
    login = int(os.getenv("MT5_LOGIN"))
    password = os.getenv("MT5_PASS")
    server = os.getenv("MT5_SERVER")
    
    print(f"🔄 Intentando conectar a: {server} (Cuenta: {login})...")
    
    if mt5.login(login, password=password, server=server):
        # 3. Obtener info de la cuenta
        cuenta_info = mt5.account_info()
        if cuenta_info:
            print("\n✅ ¡CONEXIÓN EXITOSA!")
            print(f"---------------------------")
            print(f"Broker:  {cuenta_info.company}")
            print(f"Nombre:  {cuenta_info.name}")
            print(f"Balance: {cuenta_info.balance} {cuenta_info.currency}")
            print(f"Apalancamiento: 1:{cuenta_info.leverage}")
            print(f"---------------------------")
        else:
            print("⚠️ Conectado, pero no se pudo obtener la información de la cuenta.")
    else:
        error = mt5.last_error()
        print(f"❌ Error al conectar: {error}")

    mt5.shutdown()

if __name__ == "__main__":
    probar_vinculacion()