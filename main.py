    # -*- coding: utf-8 -*-

    """
    Un bot de Telegram avanzado para la gestión del horario laboral.
    """

    import os
    import logging
    import json
    from datetime import datetime, timedelta
    from flask import Flask
    from threading import Thread
    import pytz

    from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
    from telegram.constants import ParseMode

    # --- Configuración del Servidor Web (para mantenerlo despierto) ---
    app = Flask('')

    @app.route('/')
    def home():
        return "Bot activo y funcionando."

    def run_web_server():
        app.run(host='0.0.0.0', port=8080)

    def start_web_server_thread():
        t = Thread(target=run_web_server)
        t.start()

    # --- Configuración del Bot ---
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
    )
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    MADRID_TZ = pytz.timezone('Europe/Madrid')
    DATA_FILE = "fichajes.json" # Render creará este archivo en su propio sistema.

    # --- LÓGICA DE PERSISTENCIA DE DATOS ---
    def load_data():
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_data(data):
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)

    # --- LÓGICA DEL TECLADO ---
    BOTON_ENTRAR = "✅ Fichar entrada"
    BOTON_SALIR = "❌ Fichar salida"
    BOTON_ESTADO = "ℹ️ Estado actual"
    BOTON_RESUMEN = "📊 Resumen semanal"
    REPLY_KEYBOARD = [
        [KeyboardButton(BOTON_ENTRAR), KeyboardButton(BOTON_SALIR)],
        [KeyboardButton(BOTON_ESTADO), KeyboardButton(BOTON_RESUMEN)],
    ]
    MARKUP = ReplyKeyboardMarkup(REPLY_KEYBOARD, resize_keyboard=True)

    # --- Funciones de Ayuda ---
    def format_duration(seconds):
        if seconds < 0: return "0s"
        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{int(hours)}h {int(minutes)}m"

    # --- Comandos del Bot ---
    async def comando_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if context.args and context.args[0] == "fichar":
            await context.bot.send_message(chat_id=update.effective_chat.id, text="🚀 Recibido acceso directo. Fichando entrada...")
            await comando_entrar(update, context)
            return

        nombre_usuario = update.effective_user.first_name
        await update.message.reply_text(f"¡Hola, {nombre_usuario}! 👋\n\nUsa los botones para gestionar tu jornada.", reply_markup=MARKUP)

    # ... (El resto de funciones: comando_entrar, comando_salir, etc., son las mismas que ya teníamos y funcionan perfectamente)
    async def comando_entrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = str(update.effective_chat.id)
        data = load_data()
        user_data = data.get(chat_id, {})

        if user_data.get('is_working'):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="🔴 Ya has fichado la entrada.", reply_markup=MARKUP)
            return

        hora_actual = datetime.now(MADRID_TZ)
        user_data.update({'entry_time': hora_actual.isoformat(), 'is_working': True})
        data[chat_id] = user_data
        save_data(data)

        hora_formateada = hora_actual.strftime("%H:%M:%S")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"✅ ¡Entrada registrada a las **{hora_formateada}**!", parse_mode=ParseMode.MARKDOWN, reply_markup=MARKUP)

        context.job_queue.run_once(enviar_aviso_salida, 28800, chat_id=int(chat_id), name=chat_id)

    async def comando_salir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = str(update.effective_chat.id)
        data = load_data()
        user_data = data.get(chat_id, {})

        if not user_data.get('is_working'):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="🤔 No has fichado la entrada todavía.", reply_markup=MARKUP)
            return
        
        hora_salida = datetime.now(MADRID_TZ)
        hora_entrada = datetime.fromisoformat(user_data['entry_time'])
        duracion = hora_salida - hora_entrada
        
        today_str = hora_salida.strftime('%Y-%m-%d')
        daily_logs = user_data.setdefault('daily_logs', {})
        daily_logs[today_str] = daily_logs.get(today_str, 0) + duracion.total_seconds()
        
        user_data.update({'is_working': False, 'entry_time': None})
        data[chat_id] = user_data
        save_data(data)
        
        for job in context.job_queue.get_jobs_by_name(chat_id):
            job.schedule_removal()
            
        mensaje = f"❌ Salida registrada a las **{hora_salida.strftime('%H:%M:%S')}**.\n\n⏱️ Tiempo trabajado hoy: **{format_duration(duracion.total_seconds())}**."
        await context.bot.send_message(chat_id=update.effective_chat.id, text=mensaje, parse_mode=ParseMode.MARKDOWN, reply_markup=MARKUP)

    async def comando_estado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = str(update.effective_chat.id)
        data = load_data()
        user_data = data.get(chat_id, {})

        if not user_data.get('is_working'):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="😴 No estás trabajando ahora mismo.", reply_markup=MARKUP)
            return

        hora_entrada = datetime.fromisoformat(user_data['entry_time'])
        tiempo_transcurrido = datetime.now(MADRID_TZ) - hora_entrada
        tiempo_restante = timedelta(hours=8) - tiempo_transcurrido

        mensaje = (
            f"💼 **Estado de la jornada:**\n\n"
            f"▶️ **Inicio:** {hora_entrada.strftime('%H:%M:%S')}\n"
            f"⏳ **Llevas:** {format_duration(tiempo_transcurrido.total_seconds())}\n"
            f"🏁 **Te quedan:** {format_duration(tiempo_restante.total_seconds())}"
        )
        await context.bot.send_message(chat_id=update.effective_chat.id, text=mensaje, parse_mode=ParseMode.MARKDOWN, reply_markup=MARKUP)

    async def comando_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = str(update.effective_chat.id)
        data = load_data()
        user_data = data.get(chat_id, {})
        daily_logs = user_data.get('daily_logs', {})

        if not daily_logs:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Aún no tienes registros guardados.", reply_markup=MARKUP)
            return
        
        today = datetime.now(MADRID_TZ)
        start_of_week = today - timedelta(days=today.weekday())
        dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        
        resumen_texto = "📊 **Resumen de horas de la semana:**\n\n"
        total_semanal_secs = 0

        for i in range(7):
            current_day = start_of_week + timedelta(days=i)
            day_str = current_day.strftime('%Y-%m-%d')
            seconds_worked = daily_logs.get(day_str, 0)
            if seconds_worked > 0:
                total_semanal_secs += seconds_worked
                resumen_texto += f"• **{dias_semana[i]}**: {format_duration(seconds_worked)}\n"

        resumen_texto += f"\n**Total semanal: {format_duration(total_semanal_secs)}**"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=resumen_texto, parse_mode=ParseMode.MARKDOWN, reply_markup=MARKUP)

    async def enviar_aviso_salida(context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = int(context.job.chat_id)
        mock_update = type('mock', (), {'effective_chat': type('mock', (), {'id': chat_id})})()
        await comando_salir(mock_update, context)
        
        await context.bot.send_message(chat_id=chat_id, text="🔔 **¡Han pasado 8 horas! He registrado tu salida automáticamente.**", reply_markup=MARKUP)

    # --- Función Principal ---
    def main() -> None:
        if not TELEGRAM_TOKEN:
            logging.error("No se ha encontrado el TELEGRAM_TOKEN.")
            return

        # Iniciar el servidor web en un hilo separado
        start_web_server_thread()

        # Configurar y iniciar el bot
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        application.add_handler(CommandHandler("start", comando_start))
        application.add_handler(MessageHandler(filters.TEXT & filters.Regex(f"^{BOTON_ENTRAR}$"), comando_entrar))
        application.add_handler(MessageHandler(filters.TEXT & filters.Regex(f"^{BOTON_SALIR}$"), comando_salir))
        application.add_handler(MessageHandler(filters.TEXT & filters.Regex(f"^{BOTON_ESTADO}$"), comando_estado))
        application.add_handler(MessageHandler(filters.TEXT & filters.Regex(f"^{BOTON_RESUMEN}$"), comando_resumen))

        print("🤖 El bot y el servidor web están en marcha...")
        application.run_polling()

    if __name__ == "__main__":
        main()
    ```

3.  **Crea el archivo `requirements.txt`:** En la misma carpeta, crea un archivo de texto llamado `requirements.txt` y pega dentro estas tres líneas. Es la "lista de la compra" para el servidor.
    ```text
    python-telegram-bot[job-queue]
    pytz
    Flask
    
