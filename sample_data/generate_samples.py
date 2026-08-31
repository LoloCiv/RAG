"""Script descartable: genera un set de datos ficticios pero consistente
para "Eventos Aurora" (empresa de eventos de prueba) -- varios eventos,
proveedores, presupuestos y documentos de texto, todos cruzados entre si
para poder probar bien el RAG (preguntas que requieren juntar info de mas
de un archivo) y la generacion de graficos (datos numericos reales).

No es parte de la app -- correlo una vez, subis todo a la carpeta de Drive
de prueba, y podes borrar esta carpeta despues si queres.

Genera en esta misma carpeta:
  - 5 PDFs (4 briefs de eventos + 1 de politicas generales)
  - 3 Excel (proveedores+presupuesto, directorio de proveedores, calendario)
  - 4 .txt (para pegar en Google Docs nuevos -- Drive no deja crear .docx
    nativos por script sin la API de Docs, así que se pega el texto a mano,
    es un solo copy-paste por archivo)
"""

import pandas as pd
from fpdf import FPDF

OUT_DIR = __file__.rsplit("\\", 1)[0]


# ---------------------------------------------------------------------------
# Datos base: 10 eventos de "Eventos Aurora", pasados y futuros
# ---------------------------------------------------------------------------
EVENTOS = [
    {"evento": "Casamiento Garcia-Nunez", "tipo": "Boda", "fecha": "2025-11-22", "invitados": 150, "locacion": "Quinta El Ombu", "presupuesto": 24000, "gastado": 25100, "estado": "Realizado"},
    {"evento": "Cumpleanos 50 Roberto Sanchez", "tipo": "Cumpleanos", "fecha": "2026-01-18", "invitados": 80, "locacion": "Salon Jacaranda", "presupuesto": 9000, "gastado": 8750, "estado": "Realizado"},
    {"evento": "Cumpleanos 40 Laura Diaz", "tipo": "Cumpleanos", "fecha": "2026-02-08", "invitados": 60, "locacion": "Salon Jacaranda", "presupuesto": 12000, "gastado": 10700, "estado": "Realizado"},
    {"evento": "Casamiento Perez-Gomez", "tipo": "Boda", "fecha": "2026-03-14", "invitados": 180, "locacion": "Quinta El Ombu", "presupuesto": 28000, "gastado": 28600, "estado": "Realizado"},
    {"evento": "Lanzamiento TechNova X1", "tipo": "Corporativo", "fecha": "2026-04-20", "invitados": 250, "locacion": "Centro de Convenciones Palermo", "presupuesto": 45000, "gastado": 43200, "estado": "Confirmado"},
    {"evento": "RH Summit 2026", "tipo": "Conferencia", "fecha": "2026-05-05", "invitados": 400, "locacion": "Hotel Panamericano", "presupuesto": 60000, "gastado": 0, "estado": "Planificacion"},
    {"evento": "Aniversario 15 anos Constructora Delta", "tipo": "Corporativo", "fecha": "2026-06-10", "invitados": 150, "locacion": "Salon Dorado", "presupuesto": 22000, "gastado": 0, "estado": "Planificacion"},
    {"evento": "XV Sofia Martinez", "tipo": "Quinceañera", "fecha": "2026-07-22", "invitados": 120, "locacion": "Quinta Los Alamos", "presupuesto": 18000, "gastado": 0, "estado": "Confirmado"},
    {"evento": "Casamiento Fernandez-Lopez", "tipo": "Boda", "fecha": "2026-08-30", "invitados": 220, "locacion": "Estancia La Candelaria", "presupuesto": 35000, "gastado": 0, "estado": "Confirmado"},
    {"evento": "Gala Benefica Fundacion Esperanza", "tipo": "Beneficencia", "fecha": "2026-09-12", "invitados": 300, "locacion": "Hotel Alvear", "presupuesto": 50000, "gastado": 0, "estado": "Planificacion"},
]

# Directorio de proveedores (categoria, contacto, precio promedio, rating)
DIRECTORIO_PROVEEDORES = [
    {"Proveedor": "Catering Buena Mesa", "Categoria": "Catering", "Contacto": "Roman Aguirre", "Telefono": "11-4455-0101", "Email": "roman@buenamesa.com.ar", "Precio_Promedio": 65, "Unidad": "por invitado", "Rating": 4.8},
    {"Proveedor": "Sabores del Plata", "Categoria": "Catering", "Contacto": "Estela Ferro", "Telefono": "11-4455-0102", "Email": "estela@saboresdelplata.com.ar", "Precio_Promedio": 58, "Unidad": "por invitado", "Rating": 4.5},
    {"Proveedor": "Flores del Sur", "Categoria": "Decoracion", "Contacto": "Nadia Correa", "Telefono": "11-4455-0201", "Email": "nadia@floresdelsur.com.ar", "Precio_Promedio": 2200, "Unidad": "por evento", "Rating": 4.9},
    {"Proveedor": "Flores Bouquet", "Categoria": "Decoracion", "Contacto": "Pablo Reyes", "Telefono": "11-4455-0202", "Email": "pablo@floresbouquet.com.ar", "Precio_Promedio": 1900, "Unidad": "por evento", "Rating": 4.1},
    {"Proveedor": "Los Sonidos (banda)", "Categoria": "Musica", "Contacto": "Fede Ramos", "Telefono": "11-4455-0301", "Email": "fede@lossonidos.com.ar", "Precio_Promedio": 3200, "Unidad": "por evento", "Rating": 4.7},
    {"Proveedor": "Sonido Total", "Categoria": "Musica", "Contacto": "Vicky Lamas", "Telefono": "11-4455-0302", "Email": "vicky@sonidototal.com.ar", "Precio_Promedio": 1500, "Unidad": "por evento", "Rating": 4.3},
    {"Proveedor": "DJ Marco Vidal", "Categoria": "Musica", "Contacto": "Marco Vidal", "Telefono": "11-4455-0303", "Email": "marco@djmarcovidal.com", "Precio_Promedio": 1100, "Unidad": "por evento", "Rating": 4.6},
    {"Proveedor": "Quinta El Ombu", "Categoria": "Locacion", "Contacto": "Silvia Paz", "Telefono": "11-4455-0401", "Email": "reservas@elombu.com.ar", "Precio_Promedio": 11000, "Unidad": "por evento", "Rating": 4.8},
    {"Proveedor": "Salon Jacaranda", "Categoria": "Locacion", "Contacto": "Hugo Molina", "Telefono": "11-4455-0402", "Email": "hugo@jacaranda.com.ar", "Precio_Promedio": 5500, "Unidad": "por evento", "Rating": 4.2},
    {"Proveedor": "Centro de Convenciones Palermo", "Categoria": "Locacion", "Contacto": "Marina Ibarra", "Telefono": "11-4455-0403", "Email": "eventos@ccpalermo.com.ar", "Precio_Promedio": 18000, "Unidad": "por evento", "Rating": 4.5},
    {"Proveedor": "Foto y Video Nova", "Categoria": "Fotografia", "Contacto": "Ezequiel Grimaldi", "Telefono": "11-4455-0501", "Email": "eze@fotovideonova.com.ar", "Precio_Promedio": 2800, "Unidad": "por evento", "Rating": 4.9},
    {"Proveedor": "Click Estudio", "Categoria": "Fotografia", "Contacto": "Carla Wagner", "Telefono": "11-4455-0502", "Email": "carla@clickestudio.com.ar", "Precio_Promedio": 2100, "Unidad": "por evento", "Rating": 4.4},
    {"Proveedor": "Luz y Escena", "Categoria": "Iluminacion", "Contacto": "Bruno Testa", "Telefono": "11-4455-0601", "Email": "bruno@luzyescena.com.ar", "Precio_Promedio": 1800, "Unidad": "por evento", "Rating": 4.6},
    {"Proveedor": "Seguridad Centinela", "Categoria": "Seguridad", "Contacto": "Diego Ponce", "Telefono": "11-4455-0701", "Email": "diego@centinela.com.ar", "Precio_Promedio": 45, "Unidad": "por hora/agente", "Rating": 4.3},
    {"Proveedor": "Traslados VIP", "Categoria": "Transporte", "Contacto": "Lorena Suster", "Telefono": "11-4455-0801", "Email": "lorena@trasladosvip.com.ar", "Precio_Promedio": 1200, "Unidad": "por evento", "Rating": 4.5},
    {"Proveedor": "Papeleria Fina Rossi", "Categoria": "Papeleria", "Contacto": "Julian Rossi", "Telefono": "11-4455-0901", "Email": "julian@papeleriarossi.com.ar", "Precio_Promedio": 8, "Unidad": "por invitacion", "Rating": 4.7},
    {"Proveedor": "Torteria Dulce Amor", "Categoria": "Reposteria", "Contacto": "Mercedes Vidal", "Telefono": "11-4455-1001", "Email": "mercedes@dulceamor.com.ar", "Precio_Promedio": 900, "Unidad": "por evento", "Rating": 4.9},
]

# Contrataciones reales por evento (Proveedor, Categoria, Evento, Precio) --
# el tab que alimenta charts de gasto por proveedor/categoria/evento
PROVEEDORES_POR_EVENTO = [
    # Casamiento Garcia-Nunez (2025-11-22)
    {"Proveedor": "Catering Buena Mesa", "Categoria": "Catering", "Evento": "Casamiento Garcia-Nunez", "Precio": 9750},
    {"Proveedor": "Flores Bouquet", "Categoria": "Decoracion", "Evento": "Casamiento Garcia-Nunez", "Precio": 1900},
    {"Proveedor": "Sonido Total", "Categoria": "Musica", "Evento": "Casamiento Garcia-Nunez", "Precio": 1500},
    {"Proveedor": "Quinta El Ombu", "Categoria": "Locacion", "Evento": "Casamiento Garcia-Nunez", "Precio": 11000},
    {"Proveedor": "Click Estudio", "Categoria": "Fotografia", "Evento": "Casamiento Garcia-Nunez", "Precio": 2100},
    {"Proveedor": "Torteria Dulce Amor", "Categoria": "Reposteria", "Evento": "Casamiento Garcia-Nunez", "Precio": 850},
    # Cumpleanos 50 Roberto Sanchez
    {"Proveedor": "Sabores del Plata", "Categoria": "Catering", "Evento": "Cumpleanos 50 Roberto Sanchez", "Precio": 4640},
    {"Proveedor": "DJ Marco Vidal", "Categoria": "Musica", "Evento": "Cumpleanos 50 Roberto Sanchez", "Precio": 1100},
    {"Proveedor": "Salon Jacaranda", "Categoria": "Locacion", "Evento": "Cumpleanos 50 Roberto Sanchez", "Precio": 3010},
    # Cumpleanos 40 Laura Diaz
    {"Proveedor": "Catering Buena Mesa", "Categoria": "Catering", "Evento": "Cumpleanos 40 Laura Diaz", "Precio": 4200},
    {"Proveedor": "Sonido Total", "Categoria": "Musica", "Evento": "Cumpleanos 40 Laura Diaz", "Precio": 1500},
    {"Proveedor": "Salon Jacaranda", "Categoria": "Locacion", "Evento": "Cumpleanos 40 Laura Diaz", "Precio": 5000},
    # Casamiento Perez-Gomez
    {"Proveedor": "Catering Buena Mesa", "Categoria": "Catering", "Evento": "Casamiento Perez-Gomez", "Precio": 9500},
    {"Proveedor": "Flores del Sur", "Categoria": "Decoracion", "Evento": "Casamiento Perez-Gomez", "Precio": 2100},
    {"Proveedor": "Los Sonidos (banda)", "Categoria": "Musica", "Evento": "Casamiento Perez-Gomez", "Precio": 3550},
    {"Proveedor": "Quinta El Ombu", "Categoria": "Locacion", "Evento": "Casamiento Perez-Gomez", "Precio": 11000},
    {"Proveedor": "Foto y Video Nova", "Categoria": "Fotografia", "Evento": "Casamiento Perez-Gomez", "Precio": 2800},
    {"Proveedor": "Torteria Dulce Amor", "Categoria": "Reposteria", "Evento": "Casamiento Perez-Gomez", "Precio": 950},
    # Lanzamiento TechNova X1
    {"Proveedor": "Sabores del Plata", "Categoria": "Catering", "Evento": "Lanzamiento TechNova X1", "Precio": 14500},
    {"Proveedor": "Centro de Convenciones Palermo", "Categoria": "Locacion", "Evento": "Lanzamiento TechNova X1", "Precio": 18000},
    {"Proveedor": "Luz y Escena", "Categoria": "Iluminacion", "Evento": "Lanzamiento TechNova X1", "Precio": 4200},
    {"Proveedor": "Seguridad Centinela", "Categoria": "Seguridad", "Evento": "Lanzamiento TechNova X1", "Precio": 3600},
    {"Proveedor": "Foto y Video Nova", "Categoria": "Fotografia", "Evento": "Lanzamiento TechNova X1", "Precio": 2900},
    # XV Sofia Martinez
    {"Proveedor": "Catering Buena Mesa", "Categoria": "Catering", "Evento": "XV Sofia Martinez", "Precio": 7800},
    {"Proveedor": "Flores del Sur", "Categoria": "Decoracion", "Evento": "XV Sofia Martinez", "Precio": 2400},
    {"Proveedor": "DJ Marco Vidal", "Categoria": "Musica", "Evento": "XV Sofia Martinez", "Precio": 1100},
    {"Proveedor": "Torteria Dulce Amor", "Categoria": "Reposteria", "Evento": "XV Sofia Martinez", "Precio": 1200},
]

CALENDARIO = [
    {"Evento": e["evento"], "Cliente/Area": e["evento"].split(" ")[-2] + " " + e["evento"].split(" ")[-1] if e["tipo"] in ("Boda",) else "-", "Tipo": e["tipo"], "Fecha": e["fecha"], "Invitados": e["invitados"], "Locacion": e["locacion"], "Estado": e["estado"]}
    for e in EVENTOS
]


def money(n):
    return f"USD {n:,.0f}"


# ---------------------------------------------------------------------------
# PDFs: briefs de 4 eventos "flagship" + politicas generales de la empresa
# ---------------------------------------------------------------------------
def make_pdf(filename, title, body):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 10, title)
    pdf.set_font("Helvetica", "", 11)
    pdf.ln(2)
    pdf.multi_cell(0, 7, body)
    pdf.output(f"{OUT_DIR}\\{filename}")


make_pdf(
    "Resumen_Evento_Casamiento_Perez_Gomez.pdf",
    "Resumen de Evento: Casamiento Perez-Gomez",
    """Fecha del evento: 14 de marzo de 2026
Lugar: Quinta El Ombu, Ruta 8 km 45, Pilar
Cantidad de invitados: 180
Presupuesto aprobado: USD 28,000 | Gastado real: USD 28,600

Descripcion:
Casamiento de Julieta Perez y Martin Gomez. Ceremonia religiosa a las 18:00
en el salon principal, seguida de recepcion en el jardin y cena a las 21:00.
Se contrato animacion con banda en vivo (Los Sonidos) desde las 23:00 hasta
el cierre.

Notas de planificacion:
- El cliente pidio decoracion en tonos verdes y dorados.
- Se coordino con el proveedor de catering un menu con dos opciones
  vegetarianas por el 15% de los invitados con esa dieta.
- Hubo un cambio de proveedor de flores a mitad de la planificacion, de
  Flores Bouquet a Flores del Sur, por mejor disponibilidad de paleta de
  colores (ver Contrato_Notas_Perez_Gomez para el detalle).
- El presupuesto se supero por USD 600, correspondientes a una hora extra
  de banda en vivo facturada aparte segun contrato.

Balance post-evento:
El evento se realizo sin incidentes mayores. Cliente muy conforme, dejo
reseña de 5 estrellas para Catering Buena Mesa y Foto y Video Nova.
""",
)

make_pdf(
    "Brief_Lanzamiento_TechNova_X1.pdf",
    "Brief de Evento: Lanzamiento TechNova X1",
    """Fecha del evento: 20 de abril de 2026
Lugar: Centro de Convenciones Palermo, CABA
Cantidad de invitados: 250 (prensa, clientes corporativos, staff TechNova)
Presupuesto aprobado: USD 45,000

Objetivo del evento:
Lanzamiento del producto TechNova X1 (dispositivo IoT para el hogar).
Formato: 45 min de presentacion en auditorio principal + zona de
demostracion interactiva + cocktail de cierre.

Requerimientos especiales del cliente:
- Iluminacion tipo "keynote" con pantalla LED de 12 metros (a cargo de Luz
  y Escena).
- Seguridad reforzada por presencia de prensa y personalidades (4 agentes
  de Seguridad Centinela durante las 6 horas del evento).
- Catering estilo cocktail, sin mesas sentadas, con 4 estaciones tematicas
  (a cargo de Sabores del Plata).
- Cobertura fotografica y de video para redes sociales en tiempo real
  (Foto y Video Nova).

Estado: Confirmado. Gastado a la fecha: USD 43,200 (quedan pendientes de
facturar los honorarios finales del equipo de fotografia).
""",
)

make_pdf(
    "Brief_RH_Summit_2026.pdf",
    "Brief de Evento: RH Summit 2026",
    """Fecha del evento: 5 y 6 de mayo de 2026 (2 dias)
Lugar: Hotel Panamericano, CABA
Cantidad de invitados: 400 (asistentes de RRHH de empresas asociadas)
Presupuesto aprobado: USD 60,000

Descripcion:
Conferencia anual de Recursos Humanos, con paneles, workshops y una cena de
networking el primer dia. Es el evento corporativo mas grande del
calendario de Eventos Aurora para este semestre.

Estado actual: EN PLANIFICACION. Todavia no se cerraron todos los
proveedores -- falta confirmar catering para el segundo dia y el proveedor
de traslados para los oradores internacionales.

Riesgos identificados:
- El presupuesto de USD 60,000 es ajustado para 400 personas en 2 dias con
  cena de gala incluida -- se recomienda revisar con el cliente antes de
  cerrar catering.
- 3 de los oradores confirmados llegan de vuelos internacionales el mismo
  dia del evento, coordinar con Traslados VIP con margen de contingencia.
""",
)

make_pdf(
    "Brief_XV_Sofia_Martinez.pdf",
    "Brief de Evento: XV Sofia Martinez",
    """Fecha del evento: 22 de julio de 2026
Lugar: Quinta Los Alamos
Cantidad de invitados: 120
Presupuesto aprobado: USD 18,000

Descripcion:
Fiesta de 15 anos de Sofia Martinez. Tematica elegida: "Noche de Paris".
Ceremonia de valses a las 22:00, DJ desde las 23:00.

Proveedores confirmados: Catering Buena Mesa, Flores del Sur (decoracion
tematica con torre Eiffel de utileria), DJ Marco Vidal, Torteria Dulce
Amor (torta de 4 pisos).

Estado: Confirmado. Gasto proyectado segun cotizaciones: USD 12,500,
bastante por debajo del presupuesto aprobado -- hay margen para agregar
servicio de fotografia si la familia lo solicita (todavia no contratado).
""",
)

make_pdf(
    "Politicas_Generales_Eventos_Aurora.pdf",
    "Politicas Generales - Eventos Aurora",
    """Este documento resume las politicas internas estandar que se aplican a
todos los contratos de Eventos Aurora, salvo que el contrato especifico de
un evento indique lo contrario.

Senas y pagos:
- Sena estandar: 30% al firmar el contrato.
- Saldo: 15 dias antes de la fecha del evento.
- Eventos corporativos de mas de USD 40,000: se admite un cronograma de
  pagos en 3 cuotas, sujeto a aprobacion.

Cancelaciones:
- Sin penalidad hasta 60 dias antes del evento.
- Entre 60 y 30 dias: retencion del 50% de la sena.
- Menos de 30 dias: retencion del 100% de la sena.

Cambios de proveedor:
- Cualquier cambio de proveedor ya contratado debe notificarse por escrito
  y quedar registrado en las notas de contrato del evento.
- Cambios solicitados a menos de 15 dias del evento pueden generar cargos
  adicionales segun disponibilidad.

Horas extra:
- Musica/DJ: USD 350 por hora adicional, facturado dentro de las 48hs
  posteriores al evento.
- Locacion: segun tarifa particular de cada proveedor (ver Directorio de
  Proveedores).

Contacto interno:
Coordinacion general: Ana Suarez (coordinacion@eventosaurora.com.ar)
""",
)


# ---------------------------------------------------------------------------
# Excel: 3 archivos
# ---------------------------------------------------------------------------
proveedores_evento_df = pd.DataFrame(PROVEEDORES_POR_EVENTO)
presupuesto_df = pd.DataFrame(
    [{"Evento": e["evento"], "Presupuesto_Aprobado": e["presupuesto"], "Gastado": e["gastado"], "Moneda": "USD", "Estado": e["estado"]} for e in EVENTOS]
)
with pd.ExcelWriter(f"{OUT_DIR}\\Presupuesto_Proveedores.xlsx", engine="openpyxl") as writer:
    proveedores_evento_df.to_excel(writer, sheet_name="Proveedores", index=False)
    presupuesto_df.to_excel(writer, sheet_name="Presupuesto", index=False)

directorio_df = pd.DataFrame(DIRECTORIO_PROVEEDORES)
with pd.ExcelWriter(f"{OUT_DIR}\\Directorio_Proveedores.xlsx", engine="openpyxl") as writer:
    directorio_df.to_excel(writer, sheet_name="Directorio", index=False)

calendario_df = pd.DataFrame(CALENDARIO)
with pd.ExcelWriter(f"{OUT_DIR}\\Calendario_Eventos.xlsx", engine="openpyxl") as writer:
    calendario_df.to_excel(writer, sheet_name="Calendario", index=False)


# ---------------------------------------------------------------------------
# Textos para pegar en Google Docs nuevos
# ---------------------------------------------------------------------------
with open(f"{OUT_DIR}\\Contrato_Notas_Perez_Gomez.txt", "w", encoding="utf-8") as f:
    f.write(
        """Notas de contrato: Casamiento Perez-Gomez

Cliente: Julieta Perez / Martin Gomez
Fecha de firma del contrato: 20 de enero de 2026
Evento: Casamiento Perez-Gomez, 14 de marzo de 2026, Quinta El Ombu

Terminos acordados:
- Sena del 30% al firmar (USD 8,400), saldo 15 dias antes del evento.
- Cancelacion sin penalidad hasta 60 dias antes del evento.
- Horas extra de banda en vivo: USD 350 por hora, facturadas dentro de las
  48hs posteriores al evento.

Cambios durante la planificacion:
- 10 de febrero de 2026: el cliente solicito cambiar el proveedor de
  flores original (Flores Bouquet) por Flores del Sur, por mejor
  disponibilidad de la paleta de colores pedida (verde y dorado).
- 5 de marzo de 2026: se confirmo 1 hora extra de banda en vivo para el
  cierre de la fiesta (facturada aparte, USD 350).

Contacto de emergencia del dia del evento: Coordinadora Ana Suarez.
"""
    )

with open(f"{OUT_DIR}\\Contrato_Notas_Fernandez_Lopez.txt", "w", encoding="utf-8") as f:
    f.write(
        """Notas de contrato: Casamiento Fernandez-Lopez

Cliente: Camila Fernandez / Ignacio Lopez
Fecha de firma del contrato: 2 de marzo de 2026
Evento: Casamiento Fernandez-Lopez, 30 de agosto de 2026, Estancia La
Candelaria

Terminos acordados:
- Sena del 30% al firmar (USD 10,500), saldo 15 dias antes del evento.
- El cliente pidio un cronograma de pagos especial: 30% + 30% a los 60 dias
  + 40% final -- aprobado como excepcion por tratarse de un evento de gran
  porte (220 invitados).

Pendientes de definicion (al momento de este documento):
- Proveedor de catering todavia no confirmado, en evaluacion entre
  Catering Buena Mesa y Sabores del Plata.
- Falta definir si se contrata transporte para invitados desde CABA (la
  Estancia La Candelaria queda a 90 minutos).

Contacto de emergencia del dia del evento: a definir.
"""
    )

with open(f"{OUT_DIR}\\Reporte_Post_Evento_Roberto_Sanchez.txt", "w", encoding="utf-8") as f:
    f.write(
        """Reporte post-evento: Cumpleanos 50 Roberto Sanchez

Evento realizado el 18 de enero de 2026 en Salon Jacaranda, 80 invitados.

Resumen financiero:
- Presupuesto aprobado: USD 9,000
- Gastado real: USD 8,750 (por debajo del presupuesto)
- Ahorro principal: se nego a contratar banda en vivo, DJ (Marco Vidal)
  resulto mas economico y el cliente quedo conforme igual.

Feedback del cliente:
Muy satisfecho con el catering (Sabores del Plata) y la locacion. Unico
comentario: el salon quedo con poco espacio para baile con 80 personas,
para proximos eventos similares en Salon Jacaranda conviene sugerir
maximo 65-70 invitados si se quiere pista de baile amplia.

Leccion aprendida para el equipo:
Documentar en el Directorio de Proveedores la capacidad real de baile de
cada locacion, no solo la capacidad de invitados sentados.
"""
    )

with open(f"{OUT_DIR}\\Manual_Proveedores_Preferidos.txt", "w", encoding="utf-8") as f:
    f.write(
        """Manual interno: Proveedores preferidos por categoria - Eventos Aurora

Este documento resume las recomendaciones internas del equipo de
coordinacion sobre que proveedores priorizar por categoria, en base a la
experiencia de eventos anteriores (ver Directorio_Proveedores.xlsx para
datos de contacto y precios).

Catering:
Catering Buena Mesa es el proveedor preferido para eventos sociales (bodas,
cumpleanos) por su rating mas alto (4.8) y flexibilidad con menus
especiales. Sabores del Plata es mejor opcion para eventos corporativos
grandes (formato cocktail, mas de 200 personas) por capacidad operativa.

Musica:
Los Sonidos (banda en vivo) para bodas de alto presupuesto. DJ Marco Vidal
es la opcion mas costo-efectiva y con excelente rating (4.6) para
cumpleanos y quinceañeras. Sonido Total como alternativa economica cuando
el presupuesto es ajustado.

Locacion:
Quinta El Ombu es la locacion insignia de la empresa para bodas de campo
(rating 4.8, muy buena relacion con el equipo de coordinacion). Salon
Jacaranda funciona bien para eventos de hasta 65-70 invitados con pista de
baile (ver Reporte_Post_Evento_Roberto_Sanchez para el detalle de por que
esta limitacion importa).

Advertencia general:
Flores Bouquet tiene rating mas bajo (4.1) que Flores del Sur (4.9) -- ante
la duda, priorizar Flores del Sur salvo que el cliente pida especificamente
lo contrario o Flores del Sur no tenga disponibilidad.
"""
    )


print("Listo. Archivos generados en", OUT_DIR)
print()
print("PDFs (5):")
print("  - Resumen_Evento_Casamiento_Perez_Gomez.pdf")
print("  - Brief_Lanzamiento_TechNova_X1.pdf")
print("  - Brief_RH_Summit_2026.pdf")
print("  - Brief_XV_Sofia_Martinez.pdf")
print("  - Politicas_Generales_Eventos_Aurora.pdf")
print()
print("Excel (3):")
print("  - Presupuesto_Proveedores.xlsx (tabs: Proveedores, Presupuesto -- 10 eventos, 27 contrataciones)")
print("  - Directorio_Proveedores.xlsx (17 proveedores con contacto/precio/rating)")
print("  - Calendario_Eventos.xlsx (10 eventos con fecha/estado)")
print()
print("Textos para Google Docs (4, copiar y pegar el contenido en un Doc nuevo):")
print("  - Contrato_Notas_Perez_Gomez.txt")
print("  - Contrato_Notas_Fernandez_Lopez.txt")
print("  - Reporte_Post_Evento_Roberto_Sanchez.txt")
print("  - Manual_Proveedores_Preferidos.txt")
