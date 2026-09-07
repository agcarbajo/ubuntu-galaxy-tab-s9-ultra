#!/usr/bin/python3
"""Integrated multimodal and agentic local AI application for the SM-X910."""
import ast
import base64
import datetime
import hashlib
import json
import mimetypes
import operator
import os
from pathlib import Path
import signal
import subprocess
import threading
import urllib.error
import urllib.request

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk

APP_ID = 'io.github.agcarbajo.LocalAI'
DEFAULT_MODEL = Path('/opt/gts9u-npu-llama/models/Qwen3-1.7B-Q8_0.gguf')
CATALOG_PATHS = [Path('/usr/share/gts9u-ai/model-catalog.json'),
                 Path(__file__).resolve().parent.parent / 'share/gts9u-ai/model-catalog.json']
MODELS_DIR = Path.home() / 'Modelos'
STATE_FILE = Path.home() / '.config/gts9u-ai/settings.json'
API = 'http://127.0.0.1:18080/v1/chat/completions'


class Studio(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.process = None
        self.task_process = None
        self.file_chooser = None
        self.ready = None
        self.pending_send = False
        self.retry_after_stop = False
        self.fallback_attempted = False
        self.forced_engine = None
        self.closing = False
        self.busy = False
        self.messages = []
        self.last_tool_names = []
        self.chat_model = DEFAULT_MODEL
        self.mmproj = None
        self.image_attachment = None
        self.catalog = self.load_catalog()
        self.load_state()

    def load_catalog(self):
        for path in CATALOG_PATHS:
            try:
                return json.loads(path.read_text())['models']
            except (OSError, ValueError, KeyError):
                pass
        return []

    def load_state(self):
        try:
            state = json.loads(STATE_FILE.read_text())
            model = Path(state.get('model', ''))
            if model.is_file():
                self.chat_model = model
            projector = Path(state.get('mmproj', ''))
            if projector.is_file():
                self.mmproj = projector
            self.saved_engine = int(state.get('engine', 0))
        except (OSError, ValueError):
            self.saved_engine = 0

    def save_state(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({'model': str(self.chat_model),
                                          'mmproj': str(self.mmproj or ''),
                                          'engine': self.engine.get_selected()}, indent=2))

    def do_activate(self):
        if self.props.active_window:
            self.props.active_window.present()
            return
        self.install_css()
        self.window = Gtk.ApplicationWindow(application=self, title='IA local')
        self.window.set_default_size(1180, 760)
        self.window.connect('close-request', self.close)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.window.set_child(outer)

        header = Gtk.HeaderBar()
        brand = Gtk.Box(spacing=10)
        logo = Gtk.Label(label='✦')
        logo.add_css_class('logo')
        title = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title.append(Gtk.Label(label='IA local', xalign=0, css_classes=['title-3']))
        title.append(Gtk.Label(label='Privada · en esta Galaxy Tab', xalign=0,
                               css_classes=['dim-label']))
        brand.append(logo)
        brand.append(title)
        header.set_title_widget(brand)
        self.hardware = Gtk.Label(label='NPU  Hexagon  ·  GPU  Adreno 740  ·  CPU  Kryo',
                                  css_classes=['hardware-pill'])
        header.pack_end(self.hardware)
        outer.append(header)

        body = Gtk.Box()
        body.set_vexpand(True)
        outer.append(body)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        sidebar = Gtk.StackSidebar(stack=self.stack)
        sidebar.set_size_request(210, -1)
        sidebar.add_css_class('navigation-sidebar')
        body.append(sidebar)
        body.append(self.stack)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        self.stack.add_titled(self.build_chat(), 'chat', 'Chat')
        self.stack.add_titled(self.build_media(), 'media', 'Voz e imagen')
        self.stack.add_titled(self.build_catalog(), 'models', 'Modelos')
        self.stack.add_titled(self.build_runtime(), 'runtime', 'Hardware')
        self.window.present()

    def install_css(self):
        css = b'''
        window { background: #101218; color: #f3f3f5; }
        headerbar { background: #151821; border-bottom: 1px solid #292d3a; }
        .logo { font-size: 28px; color: #a7a7ff; }
        .hardware-pill, .engine-pill { background: #282b38; border-radius: 18px; padding: 7px 13px; }
        .page-title { font-size: 24px; font-weight: 700; }
        .model-card { background: #181b24; border: 1px solid #303441; border-radius: 14px; padding: 14px; }
        .user-bubble { background: #5a45d6; border-radius: 16px; padding: 12px; margin-left: 110px; }
        .assistant-bubble { background: #20232d; border-radius: 16px; padding: 12px; margin-right: 80px; }
        .tool-bubble { background: #182b29; border-radius: 12px; padding: 9px; margin-right: 150px; }
        .composer { background: #1b1e27; border: 1px solid #363a48; border-radius: 18px; padding: 10px; }
        .status-ok { color: #78dbad; }
        .accent { color: #aaa2ff; }
        textview, textview text { background: transparent; }
        '''
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                   Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def page(self, title, subtitle):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                      margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        box.append(Gtk.Label(label=title, xalign=0, css_classes=['page-title']))
        box.append(Gtk.Label(label=subtitle, xalign=0, wrap=True, css_classes=['dim-label']))
        return box

    def build_chat(self):
        page = self.page('Conversa con tus modelos',
                         'El chat permanece en la tablet. Activa Agente para permitir herramientas locales seguras.')
        controls = Gtk.Box(spacing=10)
        self.model_label = Gtk.Label(label=self.chat_model.name, xalign=0, hexpand=True,
                                     ellipsize=3, css_classes=['accent'])
        controls.append(self.model_label)
        choose = Gtk.Button(label='Elegir GGUF')
        choose.connect('clicked', lambda *_: self.choose_file('model'))
        controls.append(choose)
        self.engine = Gtk.DropDown.new_from_strings([
            'Automático', 'NPU', 'NPU · memoria dinámica', 'NPU + CPU', 'GPU Vulkan', 'CPU'])
        self.engine.set_selected(min(self.saved_engine, 5))
        self.engine.connect('notify::selected', self.engine_changed)
        controls.append(self.engine)
        self.npu_layers = Gtk.SpinButton.new_with_range(1, 128, 1)
        self.npu_layers.set_value(20)
        self.npu_layers.set_sensitive(self.engine.get_selected() == 3)
        controls.append(self.npu_layers)
        page.append(controls)

        info = Gtk.Box(spacing=10)
        self.engine_badge = Gtk.Label(label='Sin modelo cargado', css_classes=['engine-pill'])
        info.append(self.engine_badge)
        self.agent_switch = Gtk.Switch(active=False)
        info.append(Gtk.Label(label='Agente'))
        info.append(self.agent_switch)
        self.attachment_label = Gtk.Label(label='', xalign=0, hexpand=True, css_classes=['dim-label'])
        info.append(self.attachment_label)
        unload = Gtk.Button(label='Descargar de memoria')
        unload.connect('clicked', self.cancel)
        info.append(unload)
        page.append(info)

        self.chat_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.chat_list.add_css_class('boxed-list')
        self.chat_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.chat_scroll.set_child(self.chat_list)
        page.append(self.chat_scroll)
        self.add_message('assistant', 'Hola. Puedo chatear, analizar imágenes con un VLM, usar herramientas locales y trabajar sin nube.')

        composer = Gtk.Box(spacing=8, css_classes=['composer'])
        attach = Gtk.Button(icon_name='mail-attachment-symbolic', tooltip_text='Adjuntar imagen')
        attach.connect('clicked', lambda *_: self.choose_file('attachment'))
        composer.append(attach)
        self.prompt = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False,
                                   hexpand=True, top_margin=7, bottom_margin=7)
        self.prompt.set_size_request(-1, 58)
        composer.append(self.prompt)
        self.send = Gtk.Button(label='Enviar', css_classes=['suggested-action'])
        self.send.connect('clicked', self.send_chat)
        composer.append(self.send)
        page.append(composer)
        self.chat_status = Gtk.Label(label='Listo · el modelo se carga al enviar', xalign=0,
                                     css_classes=['dim-label'])
        page.append(self.chat_status)
        return page

    def build_media(self):
        page = self.page('Voz e imagen', 'Pipelines multimodales acelerados por la NPU.')
        for icon, title, text, kind in [
                ('audio-input-microphone-symbolic', 'Transcribir audio',
                 'Whisper reconoce voz localmente con Hexagon.', 'audio'),
                ('image-x-generic-symbolic', 'Reconocer imagen',
                 'Clasificación ONNX/QNN con MobileNetV2.', 'image')]:
            card = Gtk.Box(spacing=16, css_classes=['model-card'])
            card.append(Gtk.Image.new_from_icon_name(icon))
            words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            words.append(Gtk.Label(label=title, xalign=0, css_classes=['heading']))
            words.append(Gtk.Label(label=text, xalign=0, wrap=True, css_classes=['dim-label']))
            card.append(words)
            button = Gtk.Button(label='Elegir archivo')
            button.connect('clicked', lambda _, k=kind: self.choose_file(k))
            card.append(button)
            page.append(card)
        self.media_status = Gtk.Label(label='Listo', xalign=0)
        self.media_output = Gtk.Label(label='', xalign=0, yalign=0, wrap=True, selectable=True)
        page.append(self.media_status)
        page.append(self.media_output)
        return page

    def build_catalog(self):
        page = self.page('Modelos compatibles',
                         'Selección de Hugging Face para llama.cpp. “Probado” significa medido en esta tablet.')
        scroll = Gtk.ScrolledWindow(vexpand=True)
        models = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        scroll.set_child(models)
        for item in self.catalog:
            card = Gtk.Box(spacing=12, css_classes=['model-card'])
            words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            status = '✓ Probado' if item['status'] == 'tested' else 'Por probar'
            words.append(Gtk.Label(label=f"{item['name']}  ·  {item['size']/1024**3:.1f} GB  ·  {status}",
                                   xalign=0, css_classes=['heading']))
            detail = item['class']
            if item.get('performance'):
                detail += '\n' + item['performance']
            words.append(Gtk.Label(label=detail, xalign=0, wrap=True, css_classes=['dim-label']))
            card.append(words)
            source = Gtk.Button(label='Hugging Face')
            source.connect('clicked', lambda _, url=item['page']:
                           Gio.AppInfo.launch_default_for_uri(url, None))
            card.append(source)
            local = MODELS_DIR / item['file']
            button = Gtk.Button(label='Usar' if local.is_file() else 'Descargar')
            button.connect('clicked', self.catalog_action, item)
            card.append(button)
            models.append(card)
        self.download_status = Gtk.Label(label='Las descargas se guardan en ~/Modelos.', xalign=0)
        page.append(scroll)
        page.append(self.download_status)
        return page

    def build_runtime(self):
        page = self.page('Hardware de inferencia', 'La app muestra el reparto real cuando termina de cargar cada modelo.')
        facts = [
            ('NPU', 'Hexagon HTP v73 · QNN · modelos GGUF y ONNX compatibles'),
            ('GPU', 'Adreno 740 · Mesa Turnip · Vulkan 1.4'),
            ('CPU', 'Snapdragon 8 Gen 2 · 8 núcleos · dotprod/i8mm'),
            ('Memoria', '14 GiB utilizables · ventana NPU dinámica hasta 2.8 GiB'),
            ('Compatibilidad', 'NPU preferida; GPU automática si un grafo GGUF no funciona en Hexagon')]
        for name, value in facts:
            row = Gtk.Box(spacing=14, css_classes=['model-card'])
            row.append(Gtk.Label(label=name, xalign=0, width_chars=14, css_classes=['heading']))
            row.append(Gtk.Label(label=value, xalign=0, wrap=True, hexpand=True))
            page.append(row)
        return page

    def engine_changed(self, *_):
        self.npu_layers.set_sensitive(self.engine.get_selected() == 3)
        self.forced_engine = None

    def choose_file(self, kind):
        if self.file_chooser:
            self.file_chooser.show()
            return
        title = {'model': 'Elige un modelo GGUF', 'attachment': 'Adjunta una imagen',
                 'audio': 'Elige un audio', 'image': 'Elige una imagen'}[kind]
        dialog = Gtk.FileChooserNative(title=title, transient_for=self.window,
                                       action=Gtk.FileChooserAction.OPEN,
                                       accept_label='Abrir', cancel_label='Cancelar')
        self.file_chooser = dialog
        file_filter = Gtk.FileFilter()
        if kind == 'model':
            file_filter.set_name('Modelos GGUF')
            file_filter.add_pattern('*.gguf')
        elif kind in ('attachment', 'image'):
            file_filter.set_name('Imágenes')
            file_filter.add_mime_type('image/*')
        else:
            file_filter.set_name('Audio')
            file_filter.add_mime_type('audio/*')
        dialog.add_filter(file_filter)

        def response(chooser, result):
            if result == Gtk.ResponseType.ACCEPT and chooser.get_file():
                path = Path(chooser.get_file().get_path())
                if kind == 'model':
                    self.select_model(path)
                elif kind == 'attachment':
                    self.image_attachment = path
                    self.attachment_label.set_text('Imagen: ' + path.name)
                else:
                    self.start_media(path, kind)
            chooser.destroy()
            self.file_chooser = None
        dialog.connect('response', response)
        dialog.show()

    def select_model(self, path, mmproj=None, preferred=None, recommended_layers=None):
        try:
            with path.open('rb') as source:
                if source.read(4) != b'GGUF':
                    raise ValueError('El archivo no tiene cabecera GGUF')
        except (OSError, ValueError) as exc:
            self.chat_status.set_text(str(exc))
            return
        self.cancel()
        self.forced_engine = None
        self.chat_model, self.mmproj = path, mmproj
        self.model_label.set_text(path.name)
        preferred_modes = {'auto': 0, 'npu': 1, 'window': 2, 'hybrid': 3,
                           'gpu': 4, 'cpu': 5}
        if preferred in preferred_modes:
            self.engine.set_selected(preferred_modes[preferred])
            if preferred == 'hybrid' and recommended_layers:
                self.npu_layers.set_value(recommended_layers)
        elif path.stat().st_size > 3 * 1024**3 and self.engine.get_selected() in (0, 1):
            self.engine.set_selected(2)
        self.save_state()

    def command(self):
        selected = self.engine.get_selected()
        engine = self.forced_engine or ['auto', 'npu', 'npu', 'npu', 'gpu', 'cpu'][selected]
        command = ['/usr/local/bin/gts9u-npu-app', 'chat', '--model', str(self.chat_model),
                   '--context', '2048', '--engine', engine]
        if selected == 2 or (selected == 0 and self.chat_model.stat().st_size > 3 * 1024**3):
            command += ['--memory-window']
        if selected == 3:
            command += ['--npu-layers', str(self.npu_layers.get_value_as_int())]
        if self.mmproj and self.mmproj.is_file():
            command += ['--mmproj', str(self.mmproj)]
        return command

    def start_server(self):
        if self.process is not None:
            return
        self.ready = None
        self.chat_status.set_text('Cargando modelo…')
        self.send.set_sensitive(False)
        try:
            self.process = subprocess.Popen(self.command(), stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True)
        except OSError as exc:
            self.process = None
            self.chat_status.set_text(str(exc))
            self.send.set_sensitive(True)
            return

        def worker():
            lines = []
            for line in self.process.stdout:
                lines.append(line)
                if line.startswith('READY '):
                    try:
                        ready = json.loads(line[6:])
                        GLib.idle_add(self.server_ready, ready)
                    except ValueError:
                        pass
            result = self.process.wait()
            GLib.idle_add(self.server_finished, result, ''.join(lines[-12:]))
        threading.Thread(target=worker, daemon=True).start()

    def server_ready(self, ready):
        self.ready = ready
        self.engine_badge.set_text(ready['label'] + ' · ' + ready['accelerator'])
        layers = f" · {ready['layers']}/{ready['total_layers']} capas" if ready['total_layers'] else ''
        self.chat_status.set_text('Modelo listo' + layers)
        self.send.set_sensitive(True)
        if self.pending_send:
            self.pending_send = False
            self.perform_request()
        return False

    def server_finished(self, result, tail):
        self.process = None
        was_ready = self.ready is not None
        self.ready = None
        self.send.set_sensitive(True)
        self.engine_badge.set_text('Sin modelo cargado')
        if self.retry_after_stop and not self.closing:
            self.retry_after_stop = False
            self.pending_send = True
            self.start_server()
            return False
        if result and not self.closing:
            self.chat_status.set_text('El motor se detuvo. ' + tail.strip().split('\n')[-1])
            if self.pending_send and not was_ready:
                self.pending_send = False
        elif not self.closing:
            self.chat_status.set_text('Modelo descargado de memoria')
        if self.closing:
            self.window.destroy()
        return False

    def send_chat(self, *_):
        buffer = self.prompt.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()
        if not text or self.busy:
            return
        buffer.set_text('')
        content = text
        if self.image_attachment:
            if not self.mmproj:
                self.chat_status.set_text('Este modelo no tiene proyector visual. Elige un VLM del catálogo.')
                return
            mime = mimetypes.guess_type(self.image_attachment)[0] or 'image/jpeg'
            encoded = base64.b64encode(self.image_attachment.read_bytes()).decode()
            content = [{'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{encoded}'}},
                       {'type': 'text', 'text': text}]
            self.image_attachment = None
            self.attachment_label.set_text('')
        self.messages.append({'role': 'user', 'content': content})
        self.fallback_attempted = False
        self.add_message('user', text)
        if not self.ready:
            self.pending_send = True
            self.start_server()
        else:
            self.perform_request()

    def perform_request(self):
        self.busy = True
        self.send.set_sensitive(False)
        self.chat_status.set_text('Pensando localmente…')
        history = list(self.messages)
        agent = self.agent_switch.get_active()

        def worker():
            try:
                answer, additions = self.agent_request(history, agent)
                GLib.idle_add(self.request_finished, answer, additions, None)
            except Exception as exc:
                GLib.idle_add(self.request_finished, '', [], str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def agent_request(self, history, agent):
        tools = self.tool_schema() if agent else None
        additions = []
        if agent:
            history = [{'role': 'system', 'content':
                        'Eres un agente local. Atiende siempre la petición más reciente. '
                        'Cuando uses una herramienta, incorpora su resultado en la respuesta final; '
                        'no repitas una respuesta anterior.'}] + history
        for _ in range(4):
            payload = {'messages': history, 'temperature': 0.2, 'max_tokens': 768}
            if tools:
                payload['tools'] = tools
                payload['tool_choice'] = 'auto'
            request = urllib.request.Request(API, data=json.dumps(payload).encode(),
                                             headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=180) as response:
                message = json.load(response)['choices'][0]['message']
            calls = message.get('tool_calls') or []
            if not calls:
                return message.get('content') or '(respuesta vacía)', additions
            history.append(message)
            for call in calls:
                name = call['function']['name']
                try:
                    args = json.loads(call['function'].get('arguments') or '{}')
                    result = self.run_tool(name, args)
                except Exception as exc:
                    result = 'Error de herramienta: ' + str(exc)
                additions.append((name, result))
                history.append({'role': 'tool', 'tool_call_id': call['id'], 'content': result})
        return 'He alcanzado el límite de cuatro acciones para este turno.', additions

    def tool_schema(self):
        def tool(name, description, properties=None, required=None):
            return {'type': 'function', 'function': {'name': name, 'description': description,
                    'parameters': {'type': 'object', 'properties': properties or {},
                                   'required': required or []}}}
        return [
            tool('current_time', 'Obtiene fecha y hora local de la tablet.'),
            tool('system_status', 'Consulta memoria y motor de IA actual.'),
            tool('list_local_models', 'Lista los modelos GGUF ya descargados.'),
            tool('calculator', 'Calcula una expresión aritmética.',
                 {'expression': {'type': 'string'}}, ['expression'])]

    def run_tool(self, name, args):
        if name == 'current_time':
            return datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        if name == 'system_status':
            mem = Path('/proc/meminfo').read_text().splitlines()
            available = next(x for x in mem if x.startswith('MemAvailable:'))
            return available + '; motor=' + (self.ready['label'] if self.ready else 'sin cargar')
        if name == 'list_local_models':
            models = list(MODELS_DIR.glob('*.gguf')) + list(DEFAULT_MODEL.parent.glob('*.gguf'))
            return '\n'.join(f'{p.name} ({p.stat().st_size/1024**3:.1f} GB)' for p in models)
        if name == 'calculator':
            return str(self.safe_calculate(args['expression']))
        raise ValueError('herramienta desconocida')

    def safe_calculate(self, expression):
        operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                      ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
                      ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg,
                      ast.UAdd: operator.pos}
        def evaluate(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in operations:
                return operations[type(node.op)](evaluate(node.left), evaluate(node.right))
            if isinstance(node, ast.UnaryOp) and type(node.op) in operations:
                return operations[type(node.op)](evaluate(node.operand))
            raise ValueError('expresión no permitida')
        if len(expression) > 120:
            raise ValueError('expresión demasiado larga')
        return evaluate(ast.parse(expression, mode='eval').body)

    def request_finished(self, answer, tools, error):
        self.last_tool_names = [name for name, _ in tools]
        for name, result in tools:
            self.add_message('tool', f'{name}: {result}')
        if error:
            if (self.engine.get_selected() == 0 and self.ready and
                    self.ready.get('engine') == 'npu' and not self.fallback_attempted):
                self.fallback_attempted = True
                self.forced_engine = 'gpu'
                self.retry_after_stop = True
                self.busy = False
                self.chat_status.set_text('La NPU rechazó esta operación; reintentando en GPU…')
                self.cancel()
                return False
            self.add_message('assistant', 'No pude completar la petición: ' + error)
            self.chat_status.set_text('Error de inferencia')
        else:
            self.messages.append({'role': 'assistant', 'content': answer})
            self.add_message('assistant', answer)
            self.chat_status.set_text('Respuesta generada en ' + self.ready['label'])
        self.busy = False
        self.send.set_sensitive(True)
        return False

    def add_message(self, role, text):
        frame = Gtk.Frame(css_classes=[role + '-bubble'])
        label = Gtk.Label(label=text, xalign=0, yalign=0, wrap=True, selectable=True)
        label.set_max_width_chars(95)
        frame.set_child(label)
        self.chat_list.append(frame)
        GLib.idle_add(lambda: self.chat_scroll.get_vadjustment().set_value(
            self.chat_scroll.get_vadjustment().get_upper()))

    def start_media(self, path, kind):
        if self.task_process or self.process:
            self.media_status.set_text('Descarga primero el modelo activo de memoria.')
            return
        command = (['/usr/local/bin/gts9u-ai', 'classify', str(path)] if kind == 'image' else
                   ['/usr/local/bin/gts9u-npu-app', 'transcribe', str(path)])
        self.media_status.set_text('Procesando en la NPU…')
        self.task_process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, text=True)
        def worker():
            output, _ = self.task_process.communicate()
            code = self.task_process.returncode
            GLib.idle_add(self.media_finished, kind, code, output)
        threading.Thread(target=worker, daemon=True).start()

    def media_finished(self, kind, code, output):
        self.task_process = None
        try:
            data = json.loads(output)
            text = data['text'] if kind == 'audio' else '\n'.join(
                f"{p['label']} — {p['probability']:.1%}" for p in data['predictions'])
        except (ValueError, KeyError):
            text = output
        self.media_output.set_text(text)
        self.media_status.set_text('Terminado · NPU liberada' if not code else 'No se pudo procesar')
        if self.closing:
            self.window.destroy()
        return False

    def catalog_action(self, _, item):
        button = _
        local = MODELS_DIR / Path(item['file']).name
        mmproj = MODELS_DIR / Path(item.get('mmproj_file', '')).name if item.get('mmproj_file') else None
        if local.is_file() and (not mmproj or mmproj.is_file()):
            self.select_model(local, mmproj, item.get('mode'), item.get('recommended_layers'))
            self.stack.set_visible_child_name('chat')
            return
        if button is not None:
            button.set_sensitive(False)
            button.set_label('Descargando…')
        self.download_status.set_text('Preparando descarga de ' + item['name'] + '…')
        threading.Thread(target=self.download_model, args=(item, button), daemon=True).start()

    def download_model(self, item, button=None):
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        assets = [(item['url'], MODELS_DIR / Path(item['file']).name,
                   item['size'], item['sha256'])]
        if item.get('mmproj_url'):
            assets.append((item['mmproj_url'], MODELS_DIR / Path(item['mmproj_file']).name,
                           item['mmproj_size'], item['mmproj_sha256']))
        try:
            for url, destination, expected, digest in assets:
                self.download_asset(url, destination, expected, digest, item['name'])
            projector = assets[1][1] if len(assets) > 1 else None
            GLib.idle_add(self.download_finished, item, assets[0][1], projector, button, None)
        except Exception as exc:
            GLib.idle_add(self.download_finished, item, None, None, button, str(exc))

    def download_asset(self, url, destination, expected, digest, name):
        partial = destination.with_suffix(destination.suffix + '.part')
        offset = partial.stat().st_size if partial.exists() else 0
        request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
        with urllib.request.urlopen(request, timeout=60) as response:
            append = offset and response.status == 206
            if not append:
                offset = 0
            with partial.open('ab' if append else 'wb') as target:
                while True:
                    chunk = response.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
                    offset += len(chunk)
                    percent = min(100, int(offset * 100 / expected))
                    GLib.idle_add(self.download_status.set_text,
                                  f'Descargando {name}: {percent}% · {offset/1024**3:.1f} GB')
        if partial.stat().st_size != expected:
            raise OSError(f'tamaño inesperado: {partial.stat().st_size} de {expected}')
        check = hashlib.sha256()
        with partial.open('rb') as source:
            for chunk in iter(lambda: source.read(4 * 1024 * 1024), b''):
                check.update(chunk)
        if check.hexdigest() != digest:
            raise OSError('SHA-256 incorrecto; el archivo parcial se conserva para diagnóstico')
        partial.replace(destination)

    def download_finished(self, item, model, projector, button, error):
        if error:
            self.download_status.set_text('Descarga incompleta, se puede reanudar: ' + error)
            if button is not None:
                button.set_sensitive(True)
                button.set_label('Reanudar')
        else:
            self.download_status.set_text(item['name'] + ' descargado y seleccionado.')
            if button is not None:
                button.set_sensitive(True)
                button.set_label('Usar')
            self.select_model(model, projector, item.get('mode'), item.get('recommended_layers'))
            self.stack.set_visible_child_name('chat')
        return False

    def cancel(self, *_):
        if self.process is not None:
            self.chat_status.set_text('Deteniendo y liberando el modelo…')
            self.process.send_signal(signal.SIGINT)
        if self.task_process is not None:
            self.task_process.send_signal(signal.SIGINT)

    def close(self, *_):
        if self.file_chooser:
            self.file_chooser.destroy()
            self.file_chooser = None
        if self.process is not None or self.task_process is not None:
            self.closing = True
            self.cancel()
            return True
        return False


# Gdk is imported late to keep startup errors legible on headless checks.
from gi.repository import Gdk

if __name__ == '__main__':
    Studio().run()
