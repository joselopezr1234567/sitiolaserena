const express = require('express');
const { Pool } = require('pg');
const bcrypt = require('bcryptjs');
const cors = require('cors'); // Permite que el frontend se comunique con el backend
require('dotenv').config();
const {
    WebpayPlus,
    IntegrationCommerceCodes,
    IntegrationApiKeys,
    Environment,
    Options
} = require('transbank-sdk');

const app = express();

// --- MIDDLEWARE ---
const FRONTEND_URL = process.env.FRONTEND_URL || 'http://localhost:8000';
const CORS_ORIGIN = process.env.CORS_ORIGIN || FRONTEND_URL;
const corsAllowedOrigins = CORS_ORIGIN.split(',').map(s => s.trim()).filter(Boolean);

app.use(cors({
    origin: (origin, callback) => {
        if (!origin) return callback(null, true);
        if (corsAllowedOrigins.length === 0) return callback(null, true);
        if (corsAllowedOrigins.includes('*')) return callback(null, true);
        if (corsAllowedOrigins.includes(origin)) return callback(null, true);
        return callback(new Error('Not allowed by CORS'));
    }
})); // Importante para evitar errores de bloqueo en el navegador
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

app.get('/', (req, res) => {
    res.type('text/plain').send('API sitiolaserena OK. Prueba /api/health');
});

app.get('/api/health', (req, res) => {
    res.json({ ok: true });
});

// --- CONFIGURACIÓN WEBPAY PLUS (TRANSBANK) ---
function getWebpayTransaction() {
    const env = String(process.env.TRANSBANK_ENV || '').toLowerCase();
    if (env === 'production' && process.env.TRANSBANK_COMMERCE_CODE && process.env.TRANSBANK_API_KEY) {
        const options = new Options(process.env.TRANSBANK_COMMERCE_CODE, process.env.TRANSBANK_API_KEY, Environment.Production);
        console.log('🟢 Webpay Plus configurado en PRODUCCIÓN');
        return new WebpayPlus.Transaction(options);
    }
    const options = new Options(IntegrationCommerceCodes.WEBPAY_PLUS, IntegrationApiKeys.WEBPAY, Environment.Integration);
    console.log('🧪 Webpay Plus configurado en modo INTEGRATION');
    return new WebpayPlus.Transaction(options);
}

// --- CONFIGURACIÓN DE POSTGRESQL ---
const poolConfig = process.env.DATABASE_URL
    ? {
        connectionString: process.env.DATABASE_URL,
        ssl: process.env.DB_SSL === 'false' ? false : { rejectUnauthorized: false },
    }
    : {
        user: process.env.DB_USER || 'macbook', // Local
        host: process.env.DB_HOST || 'localhost',
        database: process.env.DB_NAME || 'pizzeria_db',
        password: process.env.DB_PASSWORD || '',
        port: process.env.DB_PORT || 5432,
    };
const pool = new Pool(poolConfig);
pool.on('connect', (client) => {
    setTimeout(() => {
        client.query("SET TIME ZONE 'America/Santiago'").catch(() => {});
    }, 0);
});
// Probar conexión a la base de datos al iniciar
pool.connect((err, client, release) => {
    if (err) {
        return console.error('❌ Error adquiriendo el cliente', err.stack);
    }
    console.log('✅ Conexión a PostgreSQL establecida con éxito');
});

async function initCarritosTemporales() {
    await pool.query(`
        CREATE TABLE IF NOT EXISTS carritos_temporales (
            cart_token TEXT PRIMARY KEY,
            carrito JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    `);
    await pool.query(`DELETE FROM carritos_temporales WHERE updated_at < NOW() - INTERVAL '7 days'`);
}

initCarritosTemporales().catch((e) => console.error('Error inicializando carritos_temporales:', e.message));

async function initProductosSchema() {
    await pool.query(`ALTER TABLE productos ADD COLUMN IF NOT EXISTS combo2_disponible BOOLEAN NOT NULL DEFAULT TRUE`);
}

initProductosSchema().catch((e) => console.error('Error inicializando schema de productos:', e.message));

async function initAcompanamientosBootstrap() {
    const defaults = [
        { nombre: "PALITOS DE AJO", descripcion: "8 Palitos de Ajo + salsa de tomate", precio: 4000 },
        { nombre: "SALSA DE TOMATE", descripcion: "Salsa extra", precio: 600 },
    ];
    try {
        for (const sucursal of ["la_serena", "coquimbo"]) {
            for (const item of defaults) {
                const exists = await pool.query(
                    "SELECT id FROM productos WHERE sucursal = $1 AND lower(nombre) = lower($2) LIMIT 1",
                    [sucursal, item.nombre]
                );
                if (exists.rows.length > 0) continue;
                await pool.query(
                    "INSERT INTO productos (nombre, precio, categoria, sucursal, descripcion, disponible, combo2_disponible) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    [item.nombre, item.precio, "acompañamientos", sucursal, item.descripcion, true, true]
                );
            }
        }
        console.log("✅ Acompañamientos bootstrap OK");
    } catch (e) {
        console.error("Error creando acompañamientos bootstrap:", e?.message || e);
    }
}

initAcompanamientosBootstrap();

async function initAdminBootstrap() {
    try {
        const existing = await pool.query("SELECT id FROM usuarios WHERE rol = 'admin' LIMIT 1");
        if (existing.rows.length > 0) return;

        const adminEmail = process.env.ADMIN_EMAIL || "admin";
        const adminPassword = process.env.ADMIN_PASSWORD || "password";
        const adminNombre = process.env.ADMIN_NOMBRE || "admin";
        const adminTelefono = process.env.ADMIN_TELEFONO || "";

        const salt = await bcrypt.genSalt(10);
        const hashedPass = await bcrypt.hash(adminPassword, salt);
        await pool.query(
            "INSERT INTO usuarios (nombre, telefono, email, password, rol) VALUES ($1, $2, $3, $4, $5)",
            [adminNombre, adminTelefono, adminEmail, hashedPass, "admin"]
        );
        console.log(`✅ Admin bootstrap creado: ${adminEmail}`);
    } catch (e) {
        console.error("Error creando admin bootstrap:", e?.message || e);
    }
}

initAdminBootstrap();

// --- RUTAS DE PRODUCTOS (MENÚS) ---

// 1. Obtener productos por sucursal (Para menulaserena.html y menucoquimbo.html)
app.get('/api/productos/:sucursal', async (req, res) => {
    const { sucursal } = req.params;
    try {
        const productos = await pool.query(
            "SELECT * FROM productos WHERE sucursal = $1 AND disponible = TRUE ORDER BY categoria, nombre",
            [sucursal]
        );
        res.json(productos.rows);
    } catch (err) {
        console.error(err.message);
        res.status(500).json({ error: "Error al obtener los productos" });
    }
});

// --- RUTAS DE AUTENTICACIÓN ---

// 2. Registro de nuevos usuarios (registro.html)
app.post('/api/registro', async (req, res) => {
    const { nombre, telefono, email, password } = req.body;
    try {
        // Encriptar contraseña
        const salt = await bcrypt.genSalt(10);
        const hashedPass = await bcrypt.hash(password, salt);

        const nuevoUsuario = await pool.query(
            "INSERT INTO usuarios (nombre, telefono, email, password) VALUES ($1, $2, $3, $4) RETURNING id, nombre, email",
            [nombre, telefono, email, hashedPass]
        );
        res.json({ mensaje: "Usuario registrado", usuario: nuevoUsuario.rows[0] });
    } catch (err) {
        console.error(err.message);
        if (err.code === '23505') { // Error de email duplicado en Postgres
            res.status(400).json({ error: "El correo ya está registrado" });
        } else {
            res.status(500).json({ error: "Error en el registro" });
        }
    }
});

app.post('/api/carrito/guardar', async (req, res) => {
    const { cartToken, carrito } = req.body || {};
    if (!cartToken || typeof cartToken !== 'string') {
        return res.status(400).json({ error: 'cartToken requerido' });
    }
    if (!Array.isArray(carrito)) {
        return res.status(400).json({ error: 'carrito debe ser un array' });
    }
    try {
        await pool.query(
            `INSERT INTO carritos_temporales (cart_token, carrito, updated_at)
             VALUES ($1, $2, NOW())
             ON CONFLICT (cart_token)
             DO UPDATE SET carrito = EXCLUDED.carrito, updated_at = NOW()`,
            [cartToken, JSON.stringify(carrito)]
        );
        res.json({ ok: true });
    } catch (err) {
        console.error(err.message);
        res.status(500).json({ error: 'Error al guardar carrito' });
    }
});

app.get('/api/carrito/:cartToken', async (req, res) => {
    const { cartToken } = req.params;
    try {
        const result = await pool.query(
            'SELECT carrito FROM carritos_temporales WHERE cart_token = $1',
            [cartToken]
        );
        if (result.rows.length === 0) {
            return res.json({ carrito: [] });
        }
        res.json({ carrito: result.rows[0].carrito || [] });
    } catch (err) {
        console.error(err.message);
        res.status(500).json({ error: 'Error al obtener carrito' });
    }
});

// 3. Login de usuarios (login.html)
app.post('/api/login', async (req, res) => {
    const { email, password, cartToken } = req.body || {};
    try {
        const usuario = await pool.query("SELECT * FROM usuarios WHERE email = $1", [email]);
        
        if (usuario.rows.length === 0) {
            return res.status(400).json({ error: "Credenciales inválidas" });
        }

        const esValida = await bcrypt.compare(password, usuario.rows[0].password);
        if (!esValida) {
            return res.status(400).json({ error: "Credenciales inválidas" });
        }

        let carritoTemporal = null;
        if (cartToken && typeof cartToken === 'string') {
            try {
                const cartRes = await pool.query(
                    'SELECT carrito FROM carritos_temporales WHERE cart_token = $1',
                    [cartToken]
                );
                carritoTemporal = cartRes.rows[0]?.carrito || null;
                if (carritoTemporal) {
                    await pool.query('DELETE FROM carritos_temporales WHERE cart_token = $1', [cartToken]);
                }
            } catch (e) {
                console.error('Error recuperando carrito_temporal:', e.message);
            }
        }

        res.json({ 
            mensaje: "Login exitoso", 
            usuario: { 
                nombre: usuario.rows[0].nombre, 
                telefono: usuario.rows[0].telefono, // Incluimos el teléfono
                rol: usuario.rows[0].rol 
            },
            carrito: carritoTemporal
        });
    } catch (err) {
        console.error(err.message);
        res.status(500).json({ error: "Error en el servidor" });
    }
});

// --- RUTAS DE PEDIDOS (PARA PRODUCCIÓN) ---

// 4. Crear un nuevo pedido (carrito.html)
app.post('/api/pedidos', async (req, res) => {
    const { usuario, telefono, sucursal, productos, total } = req.body;
    try {
        // Obtener la demora actual configurada para esta sucursal
        const config = await pool.query("SELECT demora_actual FROM sucursales_config WHERE nombre = $1", [sucursal]);
        const demora = config.rows.length > 0 ? config.rows[0].demora_actual : 30;

        // Primero insertamos el pedido en la tabla 'pedidos' incluyendo la demora pactada
        const nuevoPedido = await pool.query(
            "INSERT INTO pedidos (usuario_nombre, telefono, sucursal, total, estado, demora_estimada) VALUES ($1, $2, $3, $4, 'pendiente_pago', $5) RETURNING id",
            [usuario, telefono, sucursal, total, demora]
        );
        const pedidoId = nuevoPedido.rows[0].id;

        // Luego insertamos cada producto en la tabla 'detalle_pedidos'
        for (let item of productos) {
            await pool.query(
                "INSERT INTO detalle_pedidos (pedido_id, producto_nombre, precio, detalles) VALUES ($1, $2, $3, $4)",
                [pedidoId, item.nombre, item.precio, item.detalles || '']
            );
        }

        res.json({ mensaje: "Pedido recibido con éxito", pedidoId: pedidoId });
    } catch (err) {
        console.error("Error al guardar pedido:", err.message);
        res.status(500).json({ error: "No se pudo guardar el pedido en la base de datos" });
    }
});

// 5. Obtener un pedido específico (mipedido.html)
app.get('/api/pedidos/:id', async (req, res) => {
    const { id } = req.params;
    try {
        const pedido = await pool.query("SELECT * FROM pedidos WHERE id = $1", [id]);
        if (pedido.rows.length === 0) {
            return res.status(404).json({ error: "Pedido no encontrado" });
        }
        
        const detalles = await pool.query("SELECT * FROM detalle_pedidos WHERE pedido_id = $1", [id]);
        
        res.json({
            pedido: pedido.rows[0],
            detalles: detalles.rows
        });
    } catch (err) {
        console.error(err.message);
        res.status(500).json({ error: "Error al obtener el pedido" });
    }
});

// 5.1 Obtener todos los pedidos de un usuario específico
app.get('/api/usuarios/:nombre/pedidos', async (req, res) => {
    const { nombre } = req.params;
    try {
        // Obtenemos los pedidos (ordenados por fecha descendente)
        const pedidos = await pool.query(
            "SELECT * FROM pedidos WHERE usuario_nombre = $1 ORDER BY fecha DESC", 
            [nombre]
        );
        
        // Para cada pedido, obtenemos sus detalles (usando Promise.all para eficiencia)
        const pedidosConDetalle = await Promise.all(pedidos.rows.map(async (p) => {
            const detalles = await pool.query("SELECT * FROM detalle_pedidos WHERE pedido_id = $1", [p.id]);
            return {
                ...p,
                productos: detalles.rows
            };
        }));

        res.json(pedidosConDetalle);
    } catch (err) {
        console.error(err.message);
        res.status(500).json({ error: "Error al obtener historial de pedidos" });
    }
});

// 6. Actualizar el estado de un pedido (dashboard.py)
app.put('/api/pedidos/:id/estado', async (req, res) => {
    const { id } = req.params;
    const { estado } = req.body;
    try {
        await pool.query("UPDATE pedidos SET estado = $1 WHERE id = $2", [estado, id]);
        res.json({ mensaje: "Estado del pedido actualizado" });
    } catch (err) {
        console.error(err.message);
        res.status(500).json({ error: "Error al actualizar el estado del pedido" });
    }
});

// 7. Obtener todos los pedidos pendientes para el Dashboard (con filtro opcional por sucursal y detalles de productos)
app.get('/api/admin/pedidos', async (req, res) => {
    const { sucursal } = req.query;
    try {
        let params = [];
        let query = `
            SELECT 
                id, usuario_nombre, telefono, sucursal, total, estado,
                to_char(fecha,'YYYY-MM-DD HH24:MI:SS') AS fecha_local
            FROM pedidos
            WHERE estado NOT IN ('completado', 'rechazado', 'pendiente_pago')
        `;
        if (sucursal) {
            query += " AND sucursal = $1";
            params.push(sucursal);
        }
        query += " ORDER BY fecha DESC";
        const pedidos = await pool.query(query, params);
        
        // Incluimos los detalles de productos para cada pedido
        const pedidosConDetalles = await Promise.all(pedidos.rows.map(async (p) => {
            const detalles = await pool.query("SELECT * FROM detalle_pedidos WHERE pedido_id = $1", [p.id]);
            return {
                ...p,
                fecha: p.fecha_local,
                productos: detalles.rows
            };
        }));

        res.json(pedidosConDetalles);
    } catch (err) {
        console.error(err.message);
        res.status(500).json({ error: "Error al obtener pedidos" });
    }
});

// 8. Gestionar configuración de demora por sucursal
app.get('/api/config/:sucursal', async (req, res) => {
    const { sucursal } = req.params;
    try {
        const resultado = await pool.query("SELECT * FROM sucursales_config WHERE nombre = $1", [sucursal]);
        if (resultado.rows.length === 0) {
            return res.status(404).json({ error: "Sucursal no encontrada" });
        }
        res.json(resultado.rows[0]);
    } catch (err) {
        res.status(500).json({ error: "Error al obtener configuración" });
    }
});

app.put('/api/config/:sucursal', async (req, res) => {
    const { sucursal } = req.params;
    const { demora_actual } = req.body;
    try {
        await pool.query(
            "UPDATE sucursales_config SET demora_actual = $1 WHERE nombre = $2",
            [demora_actual, sucursal]
        );
        res.json({ mensaje: "Configuración actualizada" });
    } catch (err) {
        res.status(500).json({ error: "Error al actualizar configuración" });
    }
});

// --- RUTAS DE ADMINISTRACIÓN (PRODUCTOS Y USUARIOS) ---

function requireResetToken(req, res, next) {
    if (!process.env.ADMIN_RESET_TOKEN) {
        return res.status(500).json({ error: "ADMIN_RESET_TOKEN no configurado" });
    }
    const token = req.header('x-admin-token') || req.body?.token;
    if (!token || token !== process.env.ADMIN_RESET_TOKEN) {
        return res.status(401).json({ error: "No autorizado" });
    }
    return next();
}

app.post('/api/admin/reset-db', requireResetToken, async (req, res) => {
    try {
        await pool.query("BEGIN");
        await pool.query("TRUNCATE TABLE pedidos, usuarios RESTART IDENTITY CASCADE");
        await pool.query("COMMIT");
        return res.json({ ok: true });
    } catch (err) {
        try {
            await pool.query("ROLLBACK");
        } catch {}
        console.error("Error reseteando DB:", err?.message || err);
        return res.status(500).json({ error: "No se pudo resetear la base de datos" });
    }
});

// 12. CRUD de Productos
app.get('/api/admin/productos/todos', async (req, res) => {
    try {
        const productos = await pool.query("SELECT * FROM productos ORDER BY sucursal, categoria, nombre");
        res.json(productos.rows);
    } catch (err) {
        res.status(500).json({ error: "Error al obtener productos" });
    }
});

// 4. Obtener todos los productos de una sucursal para el Admin
app.get('/api/admin/productos/:sucursal', async (req, res) => {
    const { sucursal } = req.params;
    try {
        const resultado = await pool.query(
            "SELECT * FROM productos WHERE sucursal = $1 ORDER BY id ASC",
            [sucursal]
        );
        res.json(resultado.rows);
    } catch (err) {
        res.status(500).json({ error: "Error al cargar panel admin" });
    }
});

// 5. Actualizar precio o disponibilidad (Desde el botón GUARDAR del admin)
app.put('/api/productos/:id', async (req, res) => {
    const { id } = req.params;
    const { precio, disponible } = req.body;
    try {
        await pool.query(
            "UPDATE productos SET precio = $1, disponible = $2 WHERE id = $3",
            [precio, disponible, id]
        );
        res.json({ mensaje: "Cambio guardado" });
    } catch (err) {
        res.status(500).json({ error: "No se pudo actualizar el producto" });
    }
});

// --- RUTAS DE ADMINISTRACIÓN (PRODUCTOS Y USUARIOS) ---

// 9. Obtener todos los usuarios (Solo Admin)
app.get('/api/admin/usuarios', async (req, res) => {
    try {
        const usuarios = await pool.query("SELECT id, nombre, email, telefono, rol, fecha_registro FROM usuarios ORDER BY id DESC");
        res.json(usuarios.rows);
    } catch (err) {
        res.status(500).json({ error: "Error al obtener usuarios" });
    }
});

// 10. Crear un nuevo usuario desde el Admin
app.post('/api/admin/usuarios', async (req, res) => {
    const { nombre, email, password, telefono, rol } = req.body;
    try {
        const salt = await bcrypt.genSalt(10);
        const hashedPass = await bcrypt.hash(password, salt);
        const nuevo = await pool.query(
            "INSERT INTO usuarios (nombre, email, password, telefono, rol) VALUES ($1, $2, $3, $4, $5) RETURNING id, nombre, email, rol",
            [nombre, email, hashedPass, telefono, rol]
        );
        res.json(nuevo.rows[0]);
    } catch (err) {
        res.status(500).json({ error: "Error al crear usuario" });
    }
});

// 11. Eliminar usuario
app.delete('/api/admin/usuarios/:id', async (req, res) => {
    const { id } = req.params;
    try {
        await pool.query("DELETE FROM usuarios WHERE id = $1", [id]);
        res.json({ mensaje: "Usuario eliminado" });
    } catch (err) {
        res.status(500).json({ error: "Error al eliminar usuario" });
    }
});

// 12. CRUD de Productos
app.post('/api/admin/productos', async (req, res) => {
    const { nombre, precio, categoria, sucursal, descripcion, disponible, combo2_disponible } = req.body;
    try {
        const combo2Value = combo2_disponible === undefined ? null : combo2_disponible;
        const nuevo = await pool.query(
            "INSERT INTO productos (nombre, precio, categoria, sucursal, descripcion, disponible, combo2_disponible) VALUES ($1, $2, $3, $4, $5, $6, COALESCE($7, TRUE)) RETURNING *",
            [nombre, precio, categoria, sucursal, descripcion, disponible, combo2Value]
        );
        res.json(nuevo.rows[0]);
    } catch (err) {
        res.status(500).json({ error: "Error al crear producto" });
    }
});

app.put('/api/admin/productos/:id', async (req, res) => {
    const { id } = req.params;
    const { nombre, precio, categoria, sucursal, descripcion, disponible, combo2_disponible } = req.body;
    try {
        const combo2Value = combo2_disponible === undefined ? null : combo2_disponible;
        const actualizado = await pool.query(
            "UPDATE productos SET nombre=$1, precio=$2, categoria=$3, sucursal=$4, descripcion=$5, disponible=$6, combo2_disponible=COALESCE($7, combo2_disponible) WHERE id=$8 RETURNING *",
            [nombre, precio, categoria, sucursal, descripcion, disponible, combo2Value, id]
        );
        res.json(actualizado.rows[0]);
    } catch (err) {
        res.status(500).json({ error: "Error al actualizar producto" });
    }
});

app.delete('/api/admin/productos/:id', async (req, res) => {
    const { id } = req.params;
    try {
        await pool.query("DELETE FROM productos WHERE id = $1", [id]);
        res.json({ mensaje: "Producto eliminado" });
    } catch (err) {
        res.status(500).json({ error: "Error al eliminar producto" });
    }
});

// Endpoint para Cierre de Caja
app.get('/api/admin/cierre', async (req, res) => {
    const sucursal = req.query.sucursal;
    const fecha = req.query.fecha;
    if (!sucursal) {
        return res.status(400).json({ error: "Falta parámetro sucursal" });
    }

    try {
        let fechaFiltro = null;
        if (fecha) {
            const fechaStr = String(fecha).trim();
            if (!/^\d{4}-\d{2}-\d{2}$/.test(fechaStr)) {
                return res.status(400).json({ error: "Formato de fecha inválido (YYYY-MM-DD)" });
            }
            fechaFiltro = fechaStr;
        }
        // Obtener pedidos de HOY que estén en estado 'pagado' o 'listo', con fecha local
        const resultado = await pool.query(`
            SELECT id, usuario_nombre, telefono, total,
                   to_char(fecha,'YYYY-MM-DD HH24:MI:SS') AS fecha_local,
                   estado
            FROM pedidos 
            WHERE sucursal = $1 
              AND estado IN ('pagado', 'listo') 
              AND DATE(fecha) = COALESCE($2::date, CURRENT_DATE)
            ORDER BY fecha DESC
        `, [sucursal, fechaFiltro]);

        const pedidos = resultado.rows.map(p => ({ ...p, fecha: p.fecha_local }));
        
        // Sumar el total
        const totalDia = pedidos.reduce((sum, p) => sum + (Number(p.total) || 0), 0);

        res.json({
            sucursal: sucursal,
            fecha: new Date().toISOString().split('T')[0],
            total_dia: totalDia,
            pedidos: pedidos
        });
    } catch (err) {
        console.error("Error en cierre de caja:", err);
        res.status(500).json({ error: "Error al generar cierre de caja" });
    }
});

// --- INICIAR SERVIDOR ---
const PORT = process.env.PORT || 3000;
const PUBLIC_BASE_URL = process.env.PUBLIC_BASE_URL || process.env.RENDER_EXTERNAL_URL || `http://localhost:${PORT}`;

// --- PRODUCTOS ---
app.get('/api/productos', async (req, res) => {
    const sucursal = req.query.sucursal;
    try {
        let result;
        if (sucursal) {
            result = await pool.query("SELECT * FROM productos WHERE sucursal = $1 ORDER BY categoria, nombre", [sucursal]);
        } else {
            result = await pool.query("SELECT * FROM productos ORDER BY sucursal, categoria, nombre");
        }
        res.json(result.rows);
    } catch (err) {
        console.error("Error al obtener productos:", err);
        res.status(500).json({ error: "Error al obtener productos" });
    }
});

app.put('/api/admin/productos/:id/disponibilidad', async (req, res) => {
    const { id } = req.params;
    const { disponible } = req.body;
    try {
        await pool.query("UPDATE productos SET disponible = $1 WHERE id = $2", [disponible, id]);
        res.json({ mensaje: "Disponibilidad actualizada" });
    } catch (err) {
        console.error("Error al actualizar disponibilidad:", err);
        res.status(500).json({ error: "Error al actualizar disponibilidad" });
    }
});

// --- PAGOS WEBPAY PLUS ---
// Crear transacción
app.post('/api/pagos/crear', async (req, res) => {
    const { monto, ordenId, returnUrl } = req.body || {};
    try {
        const buyOrder = String(ordenId || `ORD-${Date.now()}`);
        const sessionId = `SID-${Math.floor(Math.random() * 1e9)}`;
        const amount = Math.max(1, parseInt(monto, 10) || 0);
        const retUrl = returnUrl || `${PUBLIC_BASE_URL}/api/pagos/retorno`;

        const tx = getWebpayTransaction();
        const resp = await tx.create(buyOrder, sessionId, amount, retUrl);
        return res.json({ url: resp.url, token: resp.token, buyOrder });
    } catch (e) {
        console.error('Error creando transacción Webpay:', e?.response?.data || e.message);
        return res.status(500).json({ error: 'No se pudo iniciar el pago' });
    }
});

app.get('/api/pagos/status/:token', async (req, res) => {
    const token = req.params.token;
    try {
        const tx = getWebpayTransaction();
        const result = await tx.status(token);
        return res.json(result);
    } catch (e) {
        console.error('Error consultando estado Webpay:', e?.response?.data || e.message);
        return res.status(500).json({ error: 'No se pudo consultar el estado' });
    }
});

// Retorno de Webpay (commit)
async function manejarRetornoWebpay(req, res) {
    const token_ws = req.body?.token_ws || req.query?.token_ws;
    const tbk_token = req.body?.TBK_TOKEN || req.query?.TBK_TOKEN;
    const tbk_id_sesion = req.body?.TBK_ID_SESION || req.query?.TBK_ID_SESION;
    const tbk_orden_compra = req.body?.TBK_ORDEN_COMPRA || req.query?.TBK_ORDEN_COMPRA;

    if (!token_ws) {
        if (tbk_token || tbk_id_sesion || tbk_orden_compra) {
            const buyOrder = String(tbk_orden_compra || "");
            const pedidoId = parseInt(buyOrder, 10);
            if (!Number.isNaN(pedidoId)) {
                try {
                    await pool.query("UPDATE pedidos SET estado = $1 WHERE id = $2", ["cancelado", pedidoId]);
                } catch (e) {
                    console.error('No se pudo actualizar estado del pedido cancelado:', e.message);
                }
            }
            const destino = `${FRONTEND_URL}/mipedido.html?estado=cancelado&orden=${encodeURIComponent(buyOrder)}`;
            return res.redirect(302, destino);
        }
        return res.redirect(302, `${FRONTEND_URL}/mipedido.html?estado=error`);
    }
    try {
        const tx = getWebpayTransaction();
        const result = await tx.commit(token_ws);
        const ok = Number(result.response_code) === 0;
        const buyOrder = result.buy_order;

        // Si la orden es un ID numérico de nuestra tabla pedidos, lo actualizamos
        const pedidoId = parseInt(buyOrder, 10);
        if (!Number.isNaN(pedidoId)) {
            try {
                await pool.query("UPDATE pedidos SET estado = $1 WHERE id = $2", [ok ? 'pagado' : 'rechazado', pedidoId]);
            } catch (e) {
                console.error('No se pudo actualizar estado del pedido:', e.message);
            }
        }

        const destino = `${FRONTEND_URL}/mipedido.html?estado=${ok ? 'pagado' : 'rechazado'}&orden=${encodeURIComponent(buyOrder)}`;
        return res.redirect(302, destino);
    } catch (e) {
        console.error('Error en commit Webpay:', e?.response?.data || e.message);
        return res.redirect(302, `${FRONTEND_URL}/mipedido.html?estado=error`);
    }
}
app.post('/api/pagos/retorno', manejarRetornoWebpay);
app.get('/api/pagos/retorno', manejarRetornoWebpay);

app.listen(PORT, () => {
    console.log(`🚀 Servidor de Pizzería corriendo en ${PUBLIC_BASE_URL}`);
});
