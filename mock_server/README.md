# Mock Server IEEE 2030.5

Servidor modular para pruebas con el cliente EPRI.

## Ejecutar

```bash
cd ~/Servidor
python3 -m mock_server.app
```

## Probar

```bash
cd ~/Servidor
python3 -m unittest discover -s mock_server/tests -v
```

## Cliente

```bash
cd ~/Cliente-2030.5
./build/fase4_test eth0 http://127.0.0.1:8443/dcap
```

`servidor.py` se conserva como referencia y no es necesario para ejecutar el proyecto modular.
