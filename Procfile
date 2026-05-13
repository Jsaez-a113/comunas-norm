# Procfile — indica a Railway cómo iniciar la aplicación
# Gunicorn es el servidor WSGI de producción que reemplaza `flask run`
#
# Formato: <tipo_proceso>: <comando>
#   web   → proceso HTTP principal (Railway expone el puerto automáticamente)
#   app:app → módulo app.py, instancia Flask llamada 'app'
#   --workers 2 → 2 procesos paralelos para manejar más peticiones
#   --bind 0.0.0.0:$PORT → escuchar en todas las interfaces, puerto inyectado por Railway

web: gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT
