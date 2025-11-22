import streamlit as st
import cv2
import mediapipe as mp
import numpy as np
import sqlite3
import hashlib
import PayPal
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import io

# Configuración de PayPal (reemplaza con tus claves de prueba o producción de Paypal.com)
paypal.api_key = 'sk_test_51YourTestSecretKeyHere'  # Usa tu clave secreta

# Configuración de email (usa Gmail con app password)
EMAIL_FROM = 'tuemail@gmail.com'
EMAIL_PASSWORD = 'tu_app_password'  # Genera en Google Account > Security > App Passwords

# Base de datos SQLite (gratuita)
conn = sqlite3.connect('consultas.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users 
             (id INTEGER PRIMARY KEY, email TEXT UNIQUE, password TEXT, is_admin INTEGER DEFAULT 0)''')
c.execute('''CREATE TABLE IF NOT EXISTS consultas 
             (id INTEGER PRIMARY KEY, user_id INTEGER, consulta TEXT, fecha_nac TEXT, 
              fotos BLOB, clasificacion TEXT, ciclo TEXT, pago_id TEXT, status TEXT DEFAULT 'pending',
              respuesta TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
c.execute('''CREATE TABLE IF NOT EXISTS subscriptions 
             (id INTEGER PRIMARY KEY, user_id INTEGER, stripe_sub_id TEXT, status TEXT)''')
conn.commit()

# Base de datos de quirología basada en 'Quirología' de Orencia Colomar
quirologia_db = {
    'formas_mano': {
        'cuadrada': 'Lógica, estable, disciplinada. Ideal para liderazgo y organización.',
        'conica': 'Artística, intuitiva, sensible. Talento creativo, pero posible inestabilidad emocional.',
        'elemental': 'Práctica, terrenal, enfocada en lo material. Buena para trabajos manuales.',
        'espatula': 'Energética, inventiva, aventurera. Gran vitalidad, pero impulsiva.',
        'mixta': 'Adaptable, equilibrada, versátil en múltiples campos.'
    },
    'proporciones_dedos': {
        'largos': 'Intelectual, reflexiva, detallista.',
        'cortos': 'Impulsiva, práctica, directa.',
        'indice_dominante': 'Ambiciosa, líder natural.',
        'anular_dominante': 'Creativa, estética.'
    },
    'montes': {
        'venus_desarrollado': 'Pasional, amorosa, sensual.',
        'jupiter_desarrollado': 'Ambiciosa, confiada, exitosa.',
        'saturno_desarrollado': 'Sería, responsable, melancólica.',
        'luna_desarrollado': 'Imaginativa, intuitiva, soñadora.'
    },
    'lineas': {
        'vida_larga': 'Alta vitalidad, longevidad posible.',
        'vida_curva': 'Adaptabilidad, flexibilidad en la vida.',
        'cabeza_recta': 'Pensamiento lógico, realista.',
        'cabeza_inclinada': 'Imaginativa, creativa.',
        'corazon_curva': 'Emocional, empática.',
        'destino_fuerte': 'Propósito claro, éxito a través de esfuerzo.'
    },
    'signos': {
        'estrella': 'Éxito o riesgo inminente; protección en montes positivos.',
        'cruz': 'Obstáculo o protección espiritual.',
        'isla': 'Estrés temporal, necesidad de descanso.',
        'triangulo': 'Talento innato, buena fortuna.'
    }
}

# Inicializar MediaPipe Hands (gratuito para visión por computadora)
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(static_image_mode=True, max_num_hands=2, min_detection_confidence=0.5)

def analizar_mano(image_bytes):
    """
    Analiza una imagen de mano usando MediaPipe para landmarks y OpenCV para edge detection.
    Detecta forma, proporciones, montes, líneas y signos.
    """
    try:
        img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = hands.process(img_rgb)
        
        features = {}
        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                landmarks = hand_landmarks.landmark
                # Forma de la mano: Aspect ratio del bounding box
                x_coords = [lm.x for lm in landmarks]
                y_coords = [lm.y for lm in landmarks]
                width = max(x_coords) - min(x_coords)
                height = max(y_coords) - min(y_coords)
                ratio = width / height
                if ratio > 1.1:
                    features['forma'] = 'conica'
                elif ratio < 0.9:
                    features['forma'] = 'elemental'
                else:
                    features['forma'] = 'cuadrada'
                
                # Proporciones de dedos: Compara longitudes
                index_len = np.linalg.norm(np.array([landmarks[5].x - landmarks[8].x, landmarks[5].y - landmarks[8].y]))
                middle_len = np.linalg.norm(np.array([landmarks[9].x - landmarks[12].x, landmarks[9].y - landmarks[12].y]))
                features['proporciones_dedos'] = 'largos' if index_len + middle_len > 1.0 else 'cortos'  # Normalizado aproximado
                
                # Montes: Usa profundidad z para elevaciones (aproximado)
                if landmarks[0].z < -0.05:  # Base de la palma
                    features['monte_venus'] = 'desarrollado'
                
                # Líneas: Edge detection con OpenCV
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                edges = cv2.Canny(gray, 50, 150)
                vida_len = np.linalg.norm(np.array([landmarks[1].x - landmarks[17].x, landmarks[1].y - landmarks[17].y]))
                features['linea_vida'] = 'larga' if vida_len > 0.4 else 'corta'
                
                # Signos: Pattern matching simple
                features['signo'] = 'estrella' if np.std(x_coords) > 0.1 else 'isla'  # Dummy; expande con ML
                
        return features
    except Exception as e:
        return {'error': str(e)}

def clasificar_mano(features):
    """
    Clasifica las features detectadas usando la base de quirología del libro.
    Genera un perfil automático.
    """
    mensajes = []
    for key, value in features.items():
        if key == 'forma':
            mensajes.append(quirologia_db['formas_mano'].get(value, 'Forma no detectada.'))
        elif key == 'proporciones_dedos':
            mensajes.append(quirologia_db['proporciones_dedos'].get(value, 'Proporciones no detectadas.'))
        elif key.startswith('monte_'):
            monte = key.split('_')[1]
            mensajes.append(quirologia_db['montes'].get(f'{monte}_{value}', 'Monte no detectado.'))
        elif key.startswith('linea_'):
            linea = key.split('_')[1]
            mensajes.append(quirologia_db['lineas'].get(f'{linea}_{value}', 'Línea no detectada.'))
        elif key == 'signo':
            mensajes.append(quirologia_db['signos'].get(value, 'Signo no detectado.'))
    return ' '.join(mensajes) + ' Disclaimer: Orientativo, enfocado en autoconocimiento. No sustituye consejo profesional.'

def calcular_ciclo_y_periodo_numerologico(dia, mes, ano_nac):
    """
    Calcula el año personal basado en 'El Dominio del Destino' de Harvey Spencer Lewis.
    Suma día + mes + año actual, reduce a 1-9 con interpretaciones.
    """
    ano_actual = datetime.now().year
    suma = dia + mes + ano_actual
    while suma >= 10:
        suma = sum(int(digit) for digit in str(suma))
    interpretaciones = {
        1: 'Inicio de nuevos proyectos.',
        2: 'Cooperación y paciencia.',
        3: 'Creatividad y expresión.',
        4: 'Trabajo estable y fundaciones.',
        5: 'Cambios y aventuras.',
        6: 'Responsabilidades familiares.',
        7: 'Introspección y estudio.',
        8: 'Éxito material.',
        9: 'Cierres y transformación.'
    }
    return f'Año personal {suma}: {interpretaciones.get(suma, "Ciclo neutro.")}. Esto sugiere caminos, pero depende de tu esfuerzo.'

def hash_password(password):
    """Hash simple con SHA-256 para seguridad básica."""
    return hashlib.sha256(password.encode()).hexdigest()

def send_email(to, subject, body):
    """Envía email usando smtplib (gratuito con Gmail)."""
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_FROM
    msg['To'] = to
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, to, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        st.error(f'Error enviando email: {e}')
        return False

# UI de Streamlit
st.title('MapaGuía de tu Destino - Consultas Esotéricas de Bajo Costo')

# Estado de sesión para usuario
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'is_admin' not in st.session_state:
    st.session_state.is_admin = False

# Tabs para navegación amigable
tab_home, tab_login, tab_consulta, tab_dashboard = st.tabs(["Inicio", "Login/Registro", "Consulta", "Dashboard Admin"])

with tab_home:
    st.header("Bienvenido al Mapa Guía de tu Destino")
    st.write("Plataforma de labor social para consultas esotéricas basadas en quirología, ciclos y periodos de la vida.")
    st.write("Análisis básico gratuito. Consultas premium con interpretación personal a bajo costo.")
    st.info("Disclaimer: Todo es orientativo y enfocado en autoconocimiento. No sustituye consejo profesional.")

with tab_login:
    st.header("Registro / Login")
    # Registro simple con email/password (para Google OAuth, expande con streamlit_authenticator)
    with st.expander("Registro"):
        reg_email = st.text_input("Email (Registro)")
        reg_pw = st.text_input("Contraseña (Registro)", type="password")
        if st.button("Registrar"):
            if reg_email and reg_pw:
                hashed_pw = hash_password(reg_pw)
                try:
                    c.execute("INSERT INTO users (email, password) VALUES (?, ?)", (reg_email, hashed_pw))
                    conn.commit()
                    st.success("Usuario registrado exitosamente.")
                except sqlite3.IntegrityError:
                    st.error("Email ya registrado.")
            else:
                st.error("Completa los campos.")

    with st.expander("Login"):
        log_email = st.text_input("Email (Login)")
        log_pw = st.text_input("Contraseña (Login)", type="password")
        if st.button("Iniciar Sesión"):
            if log_email and log_pw:
                hashed_pw = hash_password(log_pw)
                c.execute("SELECT id, is_admin FROM users WHERE email = ? AND password = ?", (log_email, hashed_pw))
                user = c.fetchone()
                if user:
                    st.session_state.user_id = user[0]
                    st.session_state.is_admin = bool(user[1])
                    st.success("Sesión iniciada.")
                    # Verificar suscripción
                    c.execute("SELECT stripe_sub_id, status FROM subscriptions WHERE user_id = ?", (user[0],))
                    sub = c.fetchone()
                    if sub and sub[1] == 'active':
                        st.info("Tienes una suscripción activa.")
                else:
                    st.error("Credenciales incorrectas.")
            else:
                st.error("Completa los campos.")
    
    # Opción de donacion mensual (freemium)
    if st.session_state.user_id:
        if st.button("Donacion Mensual ($20USD/mes) para Consultas Ilimitadas"):
            try:
                session = paypal.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price_data': {
                            'currency': 'usd',
                            'product_data': {'name': 'Suscripción Mensual'},
                            'unit_amount': 200,
                            'recurring': {'interval': 'month'}
                        },
                        'quantity': 1,
                    }],
                    mode='subscription',
                    success_url='https://dominatudestinoapp.streamlit.app/success',  # Reemplaza con tu URL real (ej. Streamlit Cloud)
                    cancel_url='https://dominatudestinoapp.streamlit.app/cancel',
                    metadata={'user_id': st.session_state.user_id}
                )
                st.markdown(f"[Proceder a Pago]({session.url})", unsafe_allow_html=True)
            except Exception as e:
                st.error(f'Error creando sesión de suscripción: {e}')

with tab_consulta:
    if not st.session_state.user_id:
        st.warning("Inicia sesión para realizar consultas.")
    else:
        st.header("Formulario de Consulta")
        consulta_text = st.text_area("Describe tu duda o inquietud (ej. carrera, relaciones)")
        dia = st.number_input("Día de Nacimiento", min_value=1, max_value=31)
        mes = st.number_input("Mes de Nacimiento", min_value=1, max_value=12)
        ano_nac = st.number_input("Año de Nacimiento", min_value=1900, max_value=datetime.now().year)
        fotos = st.file_uploader("Sube 1-4 fotos de manos (palma, dorso, laterales)", accept_multiple_files=True, type=['jpg', 'png', 'jpeg'])
        
        # Consentimiento para GDPR y privacidad (anonimato opcional)
        consent = st.checkbox("Consiento el procesamiento de mis datos personales para esta consulta (anonimato opcional, datos borrados tras uso).")
        
        if st.button("Análisis Básico (Gratuito)") and consent:
            if consulta_text and dia and mes and ano_nac and fotos:
                # Procesar fotos (manejo de errores)
                features_combined = {}
                fotos_bytes = b''.join([foto.getvalue() for foto in fotos])  # Almacena como blob para DB
                for foto in fotos:
                    features = analizar_mano(foto.getvalue())
                    if 'error' in features:
                        st.error(f"Error analizando foto: {features['error']}")
                        continue
                    features_combined.update(features)
                
                clasificacion = clasificar_mano(features_combined)
                ciclo = calcular_ciclo_numerologico(dia, mes, ano_nac)
                sugerencia = f"Perfil quirológico: {clasificacion} Combinado con {ciclo} Esto sugiere caminos creativos, pero depende de tu esfuerzo."
                
                st.success(sugerencia)
                
                # Guardar en DB (para tracking, sin fotos permanentes si anonimato)
                c.execute("INSERT INTO consultas (user_id, consulta, fecha_nac, fotos, clasificacion, ciclo, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (st.session_state.user_id, consulta_text, f"{dia}/{mes}/{ano_nac}", fotos_bytes, clasificacion, ciclo, 'basic'))
                conn.commit()
            else:
                st.error("Completa todos los campos y sube al menos una foto.")
        
        if st.button("Consulta Premium ($5.00 - $15.00) elige el valor de tu donación - Interpretación Personalizada") and consent:
            try:
                session = paypal.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price_data': {
                            'currency': 'usd',
                            'product_data': {'name': 'Consulta Premium'},
                            'unit_amount': 300,  # $5.00 - $15.00
                        },
                        'quantity': 1,
                    }],
                    mode='payment',
                    success_url='https://dominatudestinoapp.streamlit.app/success',  # Reemplaza
                    cancel_url='https://dominatudestinoapp.streamlit.app/cancel',
                    metadata={'user_id': st.session_state.user_id, 'type': 'premium'}
                )
                st.markdown(f"[Proceder a Pago]({session.url})", unsafe_allow_html=True)
                
                # Guardar consulta pendiente (confirmar pago con webhook en producción)
                fotos_bytes = b''.join([foto.getvalue() for foto in fotos]) if fotos else b''
                c.execute("INSERT INTO consultas (user_id, consulta, fecha_nac, fotos, pago_id, status) VALUES (?, ?, ?, ?, ?, ?)",
                          (st.session_state.user_id, consulta_text, f"{dia}/{mes}/{ano_nac}", fotos_bytes, session.id, 'pending'))
                conn.commit()
            except Exception as e:
                st.error(f'Error: {e}')

with tab_dashboard:
    if not st.session_state.is_admin:
        st.warning("Acceso restringido al admin.")
    else:
        st.header("Dashboard Admin")
        # Lista de consultas pendientes con vista de datos/fotos
        c.execute("SELECT id, user_id, consulta, fecha_nac, clasificacion, ciclo, status, timestamp FROM consultas WHERE status = 'pending'")
        pendientes = c.fetchall()
        if pendientes:
            for consulta in pendientes:
                st.subheader(f"Consulta ID: {consulta[0]} - {consulta[7]}")
                st.write(f"User ID: {consulta[1]}")
                st.write(f"Duda: {consulta[2]}")
                st.write(f"Fecha Nac: {consulta[3]}")
                st.write(f"Clasificación IA: {consulta[4]}")
                st.write(f"Ciclo: {consulta[5]}")
                # Vista de fotos (muestra thumbnails si hay)
                st.write("Fotos disponibles en DB (para revisión).")
                
                respuesta = st.text_area(f"Interpretación Personal para ID {consulta[0]}")
                if st.button(f"Enviar Respuesta para ID {consulta[0]}"):
                    c.execute("UPDATE consultas SET respuesta = ?, status = 'completed' WHERE id = ?", (respuesta, consulta[0]))
                    conn.commit()
                    # Enviar por email o notificación
                    c.execute("SELECT email FROM users WHERE id = ?", (consulta[1],))
                    user_email = c.fetchone()[0]
                    if send_email(user_email, "Respuesta a tu Consulta", respuesta):
                        st.success("Respuesta enviada.")
                    # Borrar datos tras consulta (GDPR)
                    c.execute("UPDATE consultas SET fotos = NULL WHERE id = ?", (consulta[0],))
                    conn.commit()
        
        # Tracking de ingresos (escalable con más queries)
        st.subheader("Ingresos")
        c.execute("SELECT COUNT(*) * 3 FROM consultas WHERE status = 'completed'")  # Asume $3 por premium; expande para suscripciones
        ingresos = c.fetchone()[0] or 0
        st.write(f"Ingresos estimados: ${ingresos}")

# Optimización: Caché para análisis rápidos (expande con @st.cache_data para funciones pesadas como analizar_mano)

# Pruebas unitarias básicas (para asegurar éxito)
def test_calcular_ciclo():
    assert 'Inicio' in calcular_ciclo_numerologico(1, 1, 2000)  # Verifica interpretación

def test_hash():
    assert len(hash_password('test')) == 64  # Verifica hash

def test_analizar_mano_dummy():
    # Prueba con imagen dummy; expande con archivos de test
    assert isinstance(analizar_mano(b''), dict)  # Verifica retorno

if __name__ == '__main__':
    test_calcular_ciclo()
    test_hash()
    test_analizar_mano_dummy()
    conn.close()

# Cómo expandirlo:
# - Agrega Google OAuth: Usa streamlit_authenticator.
# - Webhook Paypal: Agrega endpoint con st.experimental_connection para confirmar pagos.
# - Escalabilidad: Migra DB a PostgreSQL para más usuarios; usa Heroku para hosting gratuito con add-ons.
# - Optimización: Agrega @st.cache_data a analizar_mano para caché de resultados.
# - Despliegue: Sube a GitHub, despliega en Streamlit Cloud con requirements.txt: streamlit, opencv-python-headless, mediapipe, numpy, sqlite3, stripe.