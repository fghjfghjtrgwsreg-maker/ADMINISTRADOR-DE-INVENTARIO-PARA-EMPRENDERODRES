import json
import os
import sqlite3
from datetime import datetime

import customtkinter as ctk
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


class BaseDatos:
    """Gestiona las operaciones de persistencia con SQLite."""

    def __init__(self, nombre_db="inventario.db"):
        self.nombre_db = nombre_db
        self.inicializar_db()

    def conexion(self):
        return sqlite3.connect(self.nombre_db)

    def inicializar_db(self):
        conn = self.conexion()
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS configuracion (
                id INTEGER PRIMARY KEY,
                nombre_empresa TEXT,
                ruta_imagen TEXT,
                theme_mode TEXT DEFAULT 'dark',
                palette_name TEXT DEFAULT 'azul',
                ultimo_guardado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT UNIQUE NOT NULL,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                cantidad INTEGER DEFAULT 0,
                precio_compra REAL DEFAULT 0,
                precio_venta REAL DEFAULT 0,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ventas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero_factura TEXT UNIQUE NOT NULL,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total REAL DEFAULT 0,
                estado TEXT DEFAULT 'completada'
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS detalles_venta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER NOT NULL,
                producto_id INTEGER NOT NULL,
                cantidad INTEGER NOT NULL,
                precio_unitario REAL NOT NULL,
                subtotal REAL NOT NULL,
                FOREIGN KEY(venta_id) REFERENCES ventas(id),
                FOREIGN KEY(producto_id) REFERENCES productos(id)
            )
            """
        )

        self._asegurar_columnas_configuracion(cursor)
        conn.commit()
        conn.close()

    def _asegurar_columnas_configuracion(self, cursor):
        cursor.execute("PRAGMA table_info(configuracion)")
        columnas = {fila[1] for fila in cursor.fetchall()}

        migraciones = {
            "theme_mode": "ALTER TABLE configuracion ADD COLUMN theme_mode TEXT DEFAULT 'dark'",
            "palette_name": "ALTER TABLE configuracion ADD COLUMN palette_name TEXT DEFAULT 'azul'",
            "ultimo_guardado": "ALTER TABLE configuracion ADD COLUMN ultimo_guardado TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }

        for nombre_columna, sql in migraciones.items():
            if nombre_columna not in columnas:
                cursor.execute(sql)

    def guardar_configuracion(self, nombre_empresa, ruta_imagen, theme_mode, palette_name):
        conn = self.conexion()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO configuracion
            (id, nombre_empresa, ruta_imagen, theme_mode, palette_name, ultimo_guardado)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, nombre_empresa, ruta_imagen, theme_mode, palette_name, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

    def obtener_configuracion(self):
        conn = self.conexion()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT nombre_empresa, ruta_imagen, theme_mode, palette_name
            FROM configuracion
            WHERE id = 1
            """
        )
        resultado = cursor.fetchone()
        conn.close()

        if not resultado:
            return None

        return {
            "nombre_empresa": resultado[0] or "",
            "ruta_imagen": resultado[1] or "",
            "theme_mode": resultado[2] or "dark",
            "palette_name": resultado[3] or "azul",
        }

    def agregar_producto(self, codigo, nombre, descripcion, cantidad, precio_venta):
        if cantidad < 0:
            return None, False, "La cantidad inicial no puede ser negativa"
        if precio_venta < 0:
            return None, False, "El precio no puede ser negativo"

        conn = self.conexion()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO productos (codigo, nombre, descripcion, cantidad, precio_venta)
                VALUES (?, ?, ?, ?, ?)
                """,
                (codigo, nombre, descripcion, cantidad, precio_venta),
            )
            conn.commit()
            producto_id = cursor.lastrowid
            conn.close()
            return producto_id, True, "Producto agregado exitosamente"
        except sqlite3.IntegrityError:
            conn.close()
            return None, False, "El codigo del producto ya existe"
        except Exception as error:
            conn.close()
            return None, False, f"Error al agregar producto: {error}"

    def obtener_productos(self):
        conn = self.conexion()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, codigo, nombre, cantidad, precio_venta, COALESCE(descripcion, '')
            FROM productos
            ORDER BY nombre
            """
        )
        productos = cursor.fetchall()
        conn.close()
        return productos

    def obtener_producto(self, producto_id):
        conn = self.conexion()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, codigo, nombre, cantidad, precio_venta, COALESCE(descripcion, '')
            FROM productos
            WHERE id = ?
            """,
            (producto_id,),
        )
        producto = cursor.fetchone()
        conn.close()
        return producto

    def actualizar_stock(self, producto_id, cantidad_delta):
        conn = self.conexion()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT cantidad FROM productos WHERE id = ?", (producto_id,))
            fila = cursor.fetchone()

            if not fila:
                conn.close()
                return False, "Producto no encontrado"

            nuevo_stock = fila[0] + cantidad_delta
            if nuevo_stock < 0:
                conn.close()
                return False, "La operacion dejaria el stock en negativo"

            cursor.execute(
                "UPDATE productos SET cantidad = ? WHERE id = ?",
                (nuevo_stock, producto_id),
            )
            conn.commit()
            conn.close()
            return True, "Stock actualizado correctamente"
        except Exception as error:
            conn.close()
            return False, f"Error al actualizar stock: {error}"

    def crear_venta(self, numero_factura, detalles):
        if not detalles:
            return None, False, "No hay articulos para registrar"

        conn = self.conexion()
        cursor = conn.cursor()

        try:
            total = sum(float(detalle["subtotal"]) for detalle in detalles)

            for detalle in detalles:
                cursor.execute("SELECT nombre, cantidad FROM productos WHERE id = ?", (detalle["producto_id"],))
                producto = cursor.fetchone()

                if not producto:
                    raise ValueError("Uno de los productos ya no existe")
                if detalle["cantidad"] <= 0:
                    raise ValueError("Todas las cantidades deben ser mayores que cero")
                if detalle["cantidad"] > producto[1]:
                    raise ValueError(f"Stock insuficiente para {producto[0]}")

            cursor.execute(
                """
                INSERT INTO ventas (numero_factura, total)
                VALUES (?, ?)
                """,
                (numero_factura, total),
            )
            venta_id = cursor.lastrowid

            for detalle in detalles:
                cursor.execute(
                    """
                    INSERT INTO detalles_venta (venta_id, producto_id, cantidad, precio_unitario, subtotal)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        venta_id,
                        detalle["producto_id"],
                        detalle["cantidad"],
                        detalle["precio_unitario"],
                        detalle["subtotal"],
                    ),
                )
                cursor.execute(
                    "UPDATE productos SET cantidad = cantidad - ? WHERE id = ?",
                    (detalle["cantidad"], detalle["producto_id"]),
                )

            conn.commit()
            conn.close()
            return venta_id, True, f"Venta registrada: {numero_factura}"
        except Exception as error:
            conn.rollback()
            conn.close()
            return None, False, f"Error al crear venta: {error}"

    def obtener_venta(self, venta_id):
        conn = self.conexion()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT numero_factura, fecha, total FROM ventas WHERE id = ?",
            (venta_id,),
        )
        venta = cursor.fetchone()

        cursor.execute(
            """
            SELECT dv.producto_id, p.nombre, dv.cantidad, dv.precio_unitario, dv.subtotal
            FROM detalles_venta dv
            JOIN productos p ON dv.producto_id = p.id
            WHERE dv.venta_id = ?
            """,
            (venta_id,),
        )
        detalles = cursor.fetchall()
        conn.close()
        return venta, detalles


class InventarioApp(ctk.CTk):
    CONFIG_PATH = "configuracion.json"

    def __init__(self):
        super().__init__()

        self.title("Sistema de Inventario y Facturacion")
        self.geometry("1200x800")
        self.minsize(960, 720)

        self.db = BaseDatos()
        self.nombre_empresa = "Sistema de Inventario"
        self.imagen_fondo = ""
        self.theme_mode = "dark"
        self.palette_name = "azul"
        self.alerta_actual = None
        self.vista_actual = "_mostrar_configuracion"

        self.paletas = {
            "azul": {
                "surface": "#102033",
                "surface_alt": "#18324a",
                "accent": "#2f80ed",
                "accent_hover": "#2566be",
                "success": "#27ae60",
                "warning": "#f39c12",
                "danger": "#e74c3c",
                "text_dark": "#102033",
            },
            "rosado": {
                "surface": "#34172b",
                "surface_alt": "#4d2340",
                "accent": "#e75480",
                "accent_hover": "#cc456f",
                "success": "#3bb273",
                "warning": "#f4b942",
                "danger": "#ff5c7a",
                "text_dark": "#2b1221",
            },
            "esmeralda": {
                "surface": "#14332d",
                "surface_alt": "#1d4a42",
                "accent": "#1abc9c",
                "accent_hover": "#169f85",
                "success": "#2ecc71",
                "warning": "#f39c12",
                "danger": "#e74c3c",
                "text_dark": "#112a25",
            },
            "sunset": {
                "surface": "#382118",
                "surface_alt": "#553126",
                "accent": "#ff7a59",
                "accent_hover": "#e16243",
                "success": "#44c47d",
                "warning": "#ffbf47",
                "danger": "#ff5b5b",
                "text_dark": "#2f1b14",
            },
        }

        self.colores = {}
        self._cargar_configuracion_guardada()
        self._aplicar_tema(reconstruir=False)
        self._crear_interfaz()
        self.actualizar_lista_productos()

    def _aplicar_tema(self, reconstruir=True):
        ctk.set_appearance_mode(self.theme_mode)
        ctk.set_default_color_theme("blue")

        paleta = self.paletas.get(self.palette_name, self.paletas["azul"])
        es_oscuro = self.theme_mode != "light"

        self.colores = {
            "bg": "#0d1117" if es_oscuro else "#f4f7fb",
            "primary": paleta["surface"] if es_oscuro else "#ffffff",
            "secondary": paleta["surface_alt"] if es_oscuro else "#e9eef5",
            "accent": paleta["accent"],
            "accent_hover": paleta["accent_hover"],
            "success": paleta["success"],
            "warning": paleta["warning"],
            "danger": paleta["danger"],
            "text": "#f6f8fb" if es_oscuro else "#18212b",
            "text_muted": "#c6d0db" if es_oscuro else "#5c6b7a",
            "text_dark": paleta["text_dark"],
            "entry": "#203446" if es_oscuro else "#ffffff",
        }

        self.configure(fg_color=self.colores["bg"])

        if reconstruir and hasattr(self, "frame_principal"):
            self.frame_principal.destroy()
            self._crear_interfaz()

    def _crear_interfaz(self):
        self.frame_principal = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_principal.pack(fill="both", expand=True, padx=12, pady=12)

        self._crear_encabezado()
        self._crear_barra_pestanas()

        self.frame_contenido = ctk.CTkFrame(
            self.frame_principal,
            fg_color=self.colores["primary"],
            corner_radius=18,
        )
        self.frame_contenido.pack(fill="both", expand=True, pady=10)

        self._abrir_vista(self.vista_actual)

    def _crear_encabezado(self):
        frame = ctk.CTkFrame(
            self.frame_principal,
            fg_color=self.colores["primary"],
            corner_radius=18,
        )
        frame.pack(fill="x", pady=(0, 10))

        self.label_empresa = ctk.CTkLabel(
            frame,
            text=self.nombre_empresa or "Sistema de Inventario",
            font=("Helvetica", 26, "bold"),
            text_color=self.colores["text"],
        )
        self.label_empresa.pack(pady=(16, 6))

        subtitulo = f"Tema: {self.theme_mode.capitalize()} | Paleta: {self.palette_name.capitalize()}"
        self.label_subtitulo = ctk.CTkLabel(
            frame,
            text=subtitulo,
            font=("Helvetica", 13),
            text_color=self.colores["text_muted"],
        )
        self.label_subtitulo.pack(pady=(0, 14))

    def _crear_barra_pestanas(self):
        frame = ctk.CTkFrame(
            self.frame_principal,
            fg_color=self.colores["secondary"],
            corner_radius=12,
        )
        frame.pack(fill="x", pady=(0, 10))

        pestanas = [
            ("Configuracion", "_mostrar_configuracion"),
            ("Productos", "_mostrar_productos"),
            ("Ventas", "_mostrar_ventas"),
            ("Reportes", "_mostrar_reportes"),
        ]

        for texto, vista in pestanas:
            boton = ctk.CTkButton(
                frame,
                text=texto,
                command=lambda destino=vista: self._abrir_vista(destino),
                width=160,
                height=42,
                font=("Helvetica", 13, "bold"),
                fg_color=self.colores["accent"],
                hover_color=self.colores["accent_hover"],
                text_color="#ffffff",
            )
            boton.pack(side="left", padx=6, pady=6)

    def _abrir_vista(self, nombre_metodo):
        self.vista_actual = nombre_metodo
        getattr(self, nombre_metodo)()

    def _limpiar_contenido(self):
        for widget in self.frame_contenido.winfo_children():
            widget.destroy()

    def _crear_card(self, parent, titulo=None):
        frame = ctk.CTkFrame(parent, fg_color=self.colores["secondary"], corner_radius=14)
        if titulo:
            ctk.CTkLabel(
                frame,
                text=titulo,
                font=("Helvetica", 15, "bold"),
                text_color=self.colores["accent"],
            ).pack(anchor="w", padx=14, pady=(14, 10))
        return frame

    def _crear_label(self, parent, texto):
        ctk.CTkLabel(
            parent,
            text=texto,
            font=("Helvetica", 12),
            text_color=self.colores["text"],
        ).pack(anchor="w", padx=12, pady=(8, 4))

    def _crear_entry(self, parent, placeholder="", valor=""):
        entry = ctk.CTkEntry(
            parent,
            height=38,
            placeholder_text=placeholder,
            fg_color=self.colores["entry"],
            text_color=self.colores["text"],
            border_color=self.colores["accent"],
        )
        entry.pack(fill="x", padx=12, pady=(0, 10))
        if valor:
            entry.insert(0, valor)
        return entry

    def _crear_boton(self, parent, texto, comando, color=None, hover=None):
        boton = ctk.CTkButton(
            parent,
            text=texto,
            command=comando,
            height=40,
            fg_color=color or self.colores["accent"],
            hover_color=hover or self.colores["accent_hover"],
            text_color="#ffffff",
            font=("Helvetica", 12, "bold"),
        )
        return boton

    def _mostrar_configuracion(self):
        self._limpiar_contenido()

        contenedor = ctk.CTkScrollableFrame(self.frame_contenido, fg_color="transparent")
        contenedor.pack(fill="both", expand=True, padx=22, pady=22)

        ctk.CTkLabel(
            contenedor,
            text="Configuracion general",
            font=("Helvetica", 22, "bold"),
            text_color=self.colores["text"],
        ).pack(anchor="w", pady=(0, 18))

        card = self._crear_card(contenedor, "Empresa y apariencia")
        card.pack(fill="x", pady=(0, 16))

        self._crear_label(card, "Nombre de la empresa")
        self.entry_empresa = self._crear_entry(card, "Ej: Mi Negocio", self.nombre_empresa)

        self._crear_label(card, "Imagen de fondo (opcional)")
        self.entry_fondo = self._crear_entry(card, "Ruta de imagen", self.imagen_fondo)

        self._crear_boton(
            card,
            "Seleccionar imagen",
            self._cargar_imagen,
            color=self.colores["success"],
            hover="#239b56",
        ).pack(fill="x", padx=12, pady=(0, 14))

        self._crear_label(card, "Modo visual")
        self.combo_modo = ctk.CTkComboBox(
            card,
            values=["dark", "light", "system"],
            state="readonly",
            height=38,
            fg_color=self.colores["entry"],
            border_color=self.colores["accent"],
            button_color=self.colores["accent"],
            button_hover_color=self.colores["accent_hover"],
            text_color=self.colores["text"],
            dropdown_fg_color=self.colores["primary"],
            dropdown_text_color=self.colores["text"],
        )
        self.combo_modo.pack(fill="x", padx=12, pady=(0, 10))
        self.combo_modo.set(self.theme_mode)

        self._crear_label(card, "Paleta de color")
        self.combo_paleta = ctk.CTkComboBox(
            card,
            values=list(self.paletas.keys()),
            state="readonly",
            height=38,
            fg_color=self.colores["entry"],
            border_color=self.colores["accent"],
            button_color=self.colores["accent"],
            button_hover_color=self.colores["accent_hover"],
            text_color=self.colores["text"],
            dropdown_fg_color=self.colores["primary"],
            dropdown_text_color=self.colores["text"],
        )
        self.combo_paleta.pack(fill="x", padx=12, pady=(0, 14))
        self.combo_paleta.set(self.palette_name)

        self._crear_boton(
            card,
            "Guardar configuracion",
            self._guardar_configuracion,
        ).pack(fill="x", padx=12, pady=(0, 16))

        info = self._crear_card(contenedor, "Paletas disponibles")
        info.pack(fill="x")

        descripcion = (
            "Azul: profesional y sobrio | Rosado: vibrante | "
            "Esmeralda: limpio y moderno | Sunset: calido y energico"
        )
        ctk.CTkLabel(
            info,
            text=descripcion,
            justify="left",
            wraplength=900,
            text_color=self.colores["text_muted"],
            font=("Helvetica", 12),
        ).pack(anchor="w", padx=14, pady=(0, 16))

    def _mostrar_productos(self):
        self._limpiar_contenido()

        contenedor = ctk.CTkScrollableFrame(self.frame_contenido, fg_color="transparent")
        contenedor.pack(fill="both", expand=True, padx=22, pady=22)

        ctk.CTkLabel(
            contenedor,
            text="Gestion de productos",
            font=("Helvetica", 22, "bold"),
            text_color=self.colores["text"],
        ).pack(anchor="w", pady=(0, 18))

        formulario = self._crear_card(contenedor, "Agregar nuevo producto")
        formulario.pack(fill="x", pady=(0, 18))

        self._crear_label(formulario, "Codigo")
        entry_codigo = self._crear_entry(formulario, "Ej: PROD001")

        self._crear_label(formulario, "Nombre")
        entry_nombre = self._crear_entry(formulario, "Nombre del producto")

        self._crear_label(formulario, "Descripcion")
        entry_descripcion = self._crear_entry(formulario, "Descripcion corta")

        self._crear_label(formulario, "Cantidad inicial")
        entry_cantidad = self._crear_entry(formulario, "Ej: 25")

        self._crear_label(formulario, "Precio de venta")
        entry_precio = self._crear_entry(formulario, "Ej: 99.99")

        def agregar_producto():
            codigo = entry_codigo.get().strip()
            nombre = entry_nombre.get().strip()
            descripcion = entry_descripcion.get().strip()
            cantidad_texto = entry_cantidad.get().strip()
            precio_texto = entry_precio.get().strip()

            if not all([codigo, nombre, cantidad_texto, precio_texto]):
                self._mostrar_alerta("Completa codigo, nombre, cantidad y precio", "warning")
                return

            try:
                cantidad = int(cantidad_texto)
                precio = float(precio_texto)
            except ValueError:
                self._mostrar_alerta("Cantidad y precio deben ser numericos", "danger")
                return

            _, exito, mensaje = self.db.agregar_producto(
                codigo,
                nombre,
                descripcion,
                cantidad,
                precio,
            )
            self._mostrar_alerta(mensaje, "success" if exito else "danger")

            if exito:
                for entry in [entry_codigo, entry_nombre, entry_descripcion, entry_cantidad, entry_precio]:
                    entry.delete(0, "end")
                self.actualizar_lista_productos()

        self._crear_boton(
            formulario,
            "Agregar producto",
            agregar_producto,
            color=self.colores["success"],
            hover="#239b56",
        ).pack(fill="x", padx=12, pady=(0, 16))

        ctk.CTkLabel(
            contenedor,
            text="Productos registrados",
            font=("Helvetica", 16, "bold"),
            text_color=self.colores["accent"],
        ).pack(anchor="w", pady=(4, 10))

        self.frame_lista_productos = ctk.CTkFrame(
            contenedor,
            fg_color=self.colores["secondary"],
            corner_radius=14,
        )
        self.frame_lista_productos.pack(fill="both", expand=True)
        self.actualizar_lista_productos()

    def actualizar_lista_productos(self):
        if not hasattr(self, "frame_lista_productos"):
            return

        for widget in self.frame_lista_productos.winfo_children():
            widget.destroy()

        productos = self.db.obtener_productos()
        if not productos:
            ctk.CTkLabel(
                self.frame_lista_productos,
                text="Sin productos registrados",
                text_color=self.colores["text_muted"],
                font=("Helvetica", 12),
            ).pack(pady=24)
            return

        encabezado = ctk.CTkFrame(
            self.frame_lista_productos,
            fg_color=self.colores["primary"],
            corner_radius=8,
        )
        encabezado.pack(fill="x", padx=10, pady=(10, 6))

        for texto in ["Codigo", "Nombre", "Stock", "Precio", "Descripcion", "Acciones"]:
            ctk.CTkLabel(
                encabezado,
                text=texto,
                font=("Helvetica", 11, "bold"),
                text_color=self.colores["accent"],
            ).pack(side="left", padx=8, pady=10, expand=True, fill="x")

        for producto in productos:
            producto_id, codigo, nombre, cantidad, precio, descripcion = producto

            fila = ctk.CTkFrame(
                self.frame_lista_productos,
                fg_color=self.colores["secondary"],
                corner_radius=8,
            )
            fila.pack(fill="x", padx=10, pady=3)

            valores = [
                codigo,
                nombre,
                str(cantidad),
                f"${precio:.2f}",
                descripcion or "-",
            ]

            for indice, valor in enumerate(valores):
                color = self.colores["success"] if indice == 3 else self.colores["text"]
                ctk.CTkLabel(
                    fila,
                    text=valor,
                    text_color=color,
                    anchor="w",
                ).pack(side="left", padx=8, pady=10, expand=True, fill="x")

            self._crear_boton(
                fila,
                "Stock",
                lambda pid=producto_id: self._editar_stock_producto(pid),
                color=self.colores["warning"],
                hover="#d68910",
            ).pack(side="left", padx=8, pady=6)

    def _editar_stock_producto(self, producto_id):
        producto = self.db.obtener_producto(producto_id)
        if not producto:
            self._mostrar_alerta("Producto no encontrado", "danger")
            return

        ventana = ctk.CTkToplevel(self)
        ventana.title("Editar stock")
        ventana.geometry("380x230")
        ventana.transient(self)
        ventana.grab_set()

        ctk.CTkLabel(
            ventana,
            text=f"{producto[2]}",
            font=("Helvetica", 16, "bold"),
            text_color=self.colores["text"],
        ).pack(pady=(18, 6))

        ctk.CTkLabel(
            ventana,
            text=f"Stock actual: {producto[3]}",
            text_color=self.colores["text_muted"],
            font=("Helvetica", 12),
        ).pack(pady=(0, 12))

        ctk.CTkLabel(
            ventana,
            text="Ingresa una cantidad positiva o negativa",
            text_color=self.colores["text"],
        ).pack(pady=(0, 6))

        entry = ctk.CTkEntry(
            ventana,
            placeholder_text="Ej: 10 o -3",
            height=38,
            fg_color=self.colores["entry"],
            text_color=self.colores["text"],
            border_color=self.colores["accent"],
        )
        entry.pack(fill="x", padx=20, pady=(0, 14))

        def guardar():
            try:
                delta = int(entry.get().strip())
            except ValueError:
                self._mostrar_alerta("Debes escribir un numero entero", "danger")
                return

            exito, mensaje = self.db.actualizar_stock(producto_id, delta)
            self._mostrar_alerta(mensaje, "success" if exito else "danger")
            if exito:
                ventana.destroy()
                self.actualizar_lista_productos()

        self._crear_boton(
            ventana,
            "Guardar stock",
            guardar,
            color=self.colores["success"],
            hover="#239b56",
        ).pack(fill="x", padx=20, pady=(0, 14))

    def _mostrar_ventas(self):
        self._limpiar_contenido()

        contenedor = ctk.CTkScrollableFrame(self.frame_contenido, fg_color="transparent")
        contenedor.pack(fill="both", expand=True, padx=22, pady=22)

        ctk.CTkLabel(
            contenedor,
            text="Nueva venta",
            font=("Helvetica", 22, "bold"),
            text_color=self.colores["text"],
        ).pack(anchor="w", pady=(0, 18))

        productos = self.db.obtener_productos()
        if not productos:
            vacio = self._crear_card(contenedor, "Sin inventario")
            vacio.pack(fill="x")
            ctk.CTkLabel(
                vacio,
                text="No hay productos disponibles para vender.",
                text_color=self.colores["text_muted"],
            ).pack(anchor="w", padx=14, pady=(0, 16))
            return

        carrito = {}
        productos_por_opcion = {}

        selector = self._crear_card(contenedor, "Agregar articulos al carrito")
        selector.pack(fill="x", pady=(0, 16))

        self._crear_label(selector, "Seleccionar producto")
        opciones_productos = []
        for producto in productos:
            etiqueta = f"{producto[2]} | Stock: {producto[3]} | ${producto[4]:.2f}"
            opciones_productos.append(etiqueta)
            productos_por_opcion[etiqueta] = producto

        combo = ctk.CTkComboBox(
            selector,
            values=opciones_productos,
            state="readonly",
            height=38,
            fg_color=self.colores["entry"],
            border_color=self.colores["accent"],
            button_color=self.colores["accent"],
            button_hover_color=self.colores["accent_hover"],
            text_color=self.colores["text"],
            dropdown_fg_color=self.colores["primary"],
            dropdown_text_color=self.colores["text"],
        )
        combo.pack(fill="x", padx=12, pady=(0, 10))
        if opciones_productos:
            combo.set(opciones_productos[0])

        self._crear_label(selector, "Cantidad")
        entry_cantidad = self._crear_entry(selector, "Cantidad")

        frame_items = self._crear_card(contenedor, "Carrito actual")
        frame_items.pack(fill="both", expand=True)
        frame_items_body = ctk.CTkFrame(frame_items, fg_color="transparent")
        frame_items_body.pack(fill="both", expand=True, padx=2, pady=(0, 2))

        def actualizar_carrito():
            for widget in frame_items_body.winfo_children():
                widget.destroy()

            if not carrito:
                ctk.CTkLabel(
                    frame_items_body,
                    text="El carrito esta vacio",
                    text_color=self.colores["text_muted"],
                    font=("Helvetica", 12),
                ).pack(anchor="w", padx=14, pady=(0, 16))
                return

            total = 0.0
            for producto_id, item in carrito.items():
                fila = ctk.CTkFrame(frame_items_body, fg_color=self.colores["primary"], corner_radius=8)
                fila.pack(fill="x", padx=14, pady=4)

                ctk.CTkLabel(
                    fila,
                    text=f"{item['nombre']} x{item['cantidad']}",
                    text_color=self.colores["text"],
                ).pack(side="left", padx=10, pady=10, expand=True, fill="x")

                ctk.CTkLabel(
                    fila,
                    text=f"${item['subtotal']:.2f}",
                    text_color=self.colores["success"],
                    font=("Helvetica", 11, "bold"),
                ).pack(side="left", padx=10, pady=10)

                self._crear_boton(
                    fila,
                    "Quitar",
                    lambda pid=producto_id: quitar_del_carrito(pid),
                    color=self.colores["danger"],
                    hover="#c0392b",
                ).pack(side="left", padx=8, pady=6)

                total += item["subtotal"]

            total_frame = ctk.CTkFrame(frame_items_body, fg_color=self.colores["accent"], corner_radius=8)
            total_frame.pack(fill="x", padx=14, pady=(8, 16))

            ctk.CTkLabel(
                total_frame,
                text=f"TOTAL: ${total:.2f}",
                text_color="#ffffff",
                font=("Helvetica", 15, "bold"),
            ).pack(pady=12)

        def quitar_del_carrito(producto_id):
            if producto_id in carrito:
                del carrito[producto_id]
                actualizar_carrito()

        def agregar_a_carrito():
            seleccion = combo.get().strip()
            if not seleccion:
                self._mostrar_alerta("Selecciona un producto", "warning")
                return
            if seleccion not in productos_por_opcion:
                self._mostrar_alerta("El producto seleccionado no es valido", "danger")
                return

            try:
                cantidad = int(entry_cantidad.get().strip())
            except ValueError:
                self._mostrar_alerta("La cantidad debe ser un numero entero", "danger")
                return

            if cantidad <= 0:
                self._mostrar_alerta("La cantidad debe ser mayor a cero", "warning")
                return

            producto = productos_por_opcion[seleccion]
            producto_id = producto[0]
            stock_disponible = producto[3]
            cantidad_actual = carrito.get(producto_id, {}).get("cantidad", 0)

            if cantidad + cantidad_actual > stock_disponible:
                self._mostrar_alerta("La cantidad supera el stock disponible", "danger")
                return

            carrito[producto_id] = {
                "nombre": producto[2],
                "cantidad": cantidad + cantidad_actual,
                "precio": producto[4],
                "subtotal": (cantidad + cantidad_actual) * producto[4],
            }

            combo.set(seleccion)
            entry_cantidad.delete(0, "end")
            self._mostrar_alerta(f"{producto[2]} agregado al carrito", "success")
            actualizar_carrito()

        self._crear_boton(
            selector,
            "Agregar al carrito",
            agregar_a_carrito,
            color=self.colores["success"],
            hover="#239b56",
        ).pack(fill="x", padx=12, pady=(0, 16))

        def completar_venta():
            if not carrito:
                self._mostrar_alerta("El carrito esta vacio", "warning")
                return

            numero_factura = f"FAC-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            detalles = [
                {
                    "producto_id": producto_id,
                    "cantidad": item["cantidad"],
                    "precio_unitario": item["precio"],
                    "subtotal": item["subtotal"],
                }
                for producto_id, item in carrito.items()
            ]

            venta_id, exito, mensaje = self.db.crear_venta(numero_factura, detalles)
            self._mostrar_alerta(mensaje, "success" if exito else "danger")

            if exito:
                self._generar_factura_pdf(venta_id)
                carrito.clear()
                self.actualizar_lista_productos()
                self._abrir_vista("_mostrar_ventas")

        self._crear_boton(
            contenedor,
            "Completar venta",
            completar_venta,
            color=self.colores["accent"],
            hover=self.colores["accent_hover"],
        ).pack(fill="x", pady=16)

        actualizar_carrito()

    def _mostrar_reportes(self):
        self._limpiar_contenido()

        contenedor = ctk.CTkScrollableFrame(self.frame_contenido, fg_color="transparent")
        contenedor.pack(fill="both", expand=True, padx=22, pady=22)

        ctk.CTkLabel(
            contenedor,
            text="Reportes",
            font=("Helvetica", 22, "bold"),
            text_color=self.colores["text"],
        ).pack(anchor="w", pady=(0, 18))

        productos = self.db.obtener_productos()
        total_stock = sum(producto[3] for producto in productos)
        valor_total = sum(producto[3] * producto[4] for producto in productos)
        stock_bajo = [producto for producto in productos if producto[3] <= 5]

        stats = self._crear_card(contenedor, "Resumen")
        stats.pack(fill="x", pady=(0, 16))

        datos = [
            ("Total de productos", str(len(productos)), self.colores["accent"]),
            ("Unidades en stock", str(total_stock), self.colores["success"]),
            ("Valor del inventario", f"${valor_total:.2f}", self.colores["warning"]),
            ("Productos con stock bajo", str(len(stock_bajo)), self.colores["danger"]),
        ]

        for titulo, valor, color in datos:
            bloque = ctk.CTkFrame(stats, fg_color=self.colores["primary"], corner_radius=10)
            bloque.pack(fill="x", padx=14, pady=6)

            ctk.CTkLabel(
                bloque,
                text=titulo,
                text_color=self.colores["text_muted"],
                font=("Helvetica", 11),
            ).pack(anchor="w", padx=12, pady=(10, 4))

            ctk.CTkLabel(
                bloque,
                text=valor,
                text_color=color,
                font=("Helvetica", 17, "bold"),
            ).pack(anchor="w", padx=12, pady=(0, 10))

        bajos = self._crear_card(contenedor, "Alerta de stock bajo")
        bajos.pack(fill="x")

        if not stock_bajo:
            ctk.CTkLabel(
                bajos,
                text="Todo el inventario esta por encima del umbral minimo.",
                text_color=self.colores["text_muted"],
            ).pack(anchor="w", padx=14, pady=(0, 16))
            return

        for producto in stock_bajo:
            ctk.CTkLabel(
                bajos,
                text=f"{producto[2]} | Codigo: {producto[1]} | Stock: {producto[3]}",
                text_color=self.colores["text"],
            ).pack(anchor="w", padx=14, pady=4)

    def _cargar_imagen(self):
        import tkinter.filedialog as filedialog

        path = filedialog.askopenfilename(
            title="Seleccionar imagen",
            filetypes=[("Imagenes", "*.png *.jpg *.jpeg *.gif *.webp")],
        )
        if path and hasattr(self, "entry_fondo"):
            self.entry_fondo.delete(0, "end")
            self.entry_fondo.insert(0, path)

    def _guardar_configuracion(self):
        nombre = self.entry_empresa.get().strip()
        ruta_imagen = self.entry_fondo.get().strip()
        theme_mode = self.combo_modo.get().strip() or "dark"
        palette_name = self.combo_paleta.get().strip() or "azul"

        if not nombre:
            self._mostrar_alerta("Ingresa el nombre de la empresa", "warning")
            return

        if ruta_imagen and not os.path.exists(ruta_imagen):
            self._mostrar_alerta("La ruta de imagen no existe", "warning")
            return

        self.nombre_empresa = nombre
        self.imagen_fondo = ruta_imagen
        self.theme_mode = theme_mode
        self.palette_name = palette_name

        self.db.guardar_configuracion(nombre, ruta_imagen, theme_mode, palette_name)
        self._guardar_json()
        self._aplicar_tema(reconstruir=True)
        self.label_empresa.configure(text=self.nombre_empresa)
        self.label_subtitulo.configure(
            text=f"Tema: {self.theme_mode.capitalize()} | Paleta: {self.palette_name.capitalize()}"
        )
        self._mostrar_alerta("Configuracion guardada correctamente", "success")

    def _guardar_json(self):
        data = {
            "nombre_empresa": self.nombre_empresa,
            "imagen_fondo": self.imagen_fondo,
            "theme_mode": self.theme_mode,
            "palette_name": self.palette_name,
            "ultima_actualizacion": datetime.now().isoformat(),
        }
        with open(self.CONFIG_PATH, "w", encoding="utf-8") as archivo:
            json.dump(data, archivo, ensure_ascii=False, indent=2)

    def _cargar_configuracion_guardada(self):
        config_db = self.db.obtener_configuracion()
        config_json = {}

        if os.path.exists(self.CONFIG_PATH):
            try:
                with open(self.CONFIG_PATH, "r", encoding="utf-8") as archivo:
                    config_json = json.load(archivo)
            except Exception:
                config_json = {}

        config = config_db or config_json or {}
        self.nombre_empresa = config.get("nombre_empresa") or self.nombre_empresa
        self.imagen_fondo = config.get("ruta_imagen") or config.get("imagen_fondo") or ""
        self.theme_mode = config.get("theme_mode") or "dark"
        self.palette_name = config.get("palette_name") or "azul"

    def _generar_factura_pdf(self, venta_id):
        try:
            venta, detalles = self.db.obtener_venta(venta_id)
            if not venta:
                self._mostrar_alerta("No se encontro la venta para generar la factura", "danger")
                return

            numero_factura, fecha, total = venta
            nombre_archivo = f"Factura_{numero_factura}.pdf"

            doc = SimpleDocTemplate(nombre_archivo, pagesize=letter)
            story = []
            styles = getSampleStyleSheet()

            estilo_titulo = ParagraphStyle(
                "TituloFactura",
                parent=styles["Heading1"],
                fontSize=20,
                textColor=colors.HexColor(self.colores["accent"]),
                alignment=1,
                spaceAfter=18,
            )

            story.append(Paragraph(self.nombre_empresa or "Factura", estilo_titulo))
            story.append(Spacer(1, 0.18 * inch))

            info_data = [
                ["Factura", numero_factura],
                ["Fecha", str(fecha)],
                ["Total", f"${total:.2f}"],
            ]
            info_table = Table(info_data, colWidths=[2 * inch, 4.1 * inch])
            info_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor(self.colores["accent"])),
                        ("TEXTCOLOR", (0, 0), (0, -1), colors.whitesmoke),
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("GRID", (0, 0), (-1, -1), 1, colors.grey),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            story.append(info_table)
            story.append(Spacer(1, 0.28 * inch))

            data = [["Producto", "Cantidad", "Precio Unit.", "Subtotal"]]
            for detalle in detalles:
                data.append(
                    [
                        detalle[1],
                        str(detalle[2]),
                        f"${detalle[3]:.2f}",
                        f"${detalle[4]:.2f}",
                    ]
                )

            detalle_table = Table(data, colWidths=[2.9 * inch, 1.1 * inch, 1.25 * inch, 1.25 * inch])
            detalle_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(self.colores["accent"])),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                        ("GRID", (0, 0), (-1, -1), 1, colors.grey),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                    ]
                )
            )
            story.append(detalle_table)
            story.append(Spacer(1, 0.24 * inch))

            estilo_total = ParagraphStyle(
                "TotalFactura",
                parent=styles["Heading2"],
                fontSize=14,
                textColor=colors.HexColor("#1f8f55"),
                alignment=2,
            )
            story.append(Paragraph(f"<b>TOTAL: ${total:.2f}</b>", estilo_total))

            doc.build(story)
            self._mostrar_alerta(f"Factura generada: {nombre_archivo}", "success")
        except Exception as error:
            self._mostrar_alerta(f"Error al generar factura: {error}", "danger")

    def _mostrar_alerta(self, mensaje, tipo="info"):
        colores_alerta = {
            "success": self.colores["success"],
            "warning": self.colores["warning"],
            "danger": self.colores["danger"],
            "info": self.colores["accent"],
        }

        if self.alerta_actual is not None and self.alerta_actual.winfo_exists():
            self.alerta_actual.destroy()

        self.alerta_actual = ctk.CTkFrame(
            self.frame_principal,
            fg_color=colores_alerta.get(tipo, self.colores["accent"]),
            corner_radius=10,
        )
        self.alerta_actual.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            self.alerta_actual,
            text=mensaje,
            text_color="#ffffff",
            font=("Helvetica", 12, "bold"),
        ).pack(padx=16, pady=10)

        self.after(3200, self._cerrar_alerta)

    def _cerrar_alerta(self):
        if self.alerta_actual is not None and self.alerta_actual.winfo_exists():
            self.alerta_actual.destroy()
        self.alerta_actual = None


if __name__ == "__main__":
    app = InventarioApp()
    app.mainloop()
