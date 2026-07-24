const express = require('express');
const { Pool } = require('pg');
const bcrypt = require('bcryptjs');
const cors = require('cors'); // Permite que el frontend se comunique con el backend
const https = require('https');
const crypto = require('crypto');
require('dotenv').config();

// Configuración de zona horaria para PostgreSQL
process.env.PGTZ = 'America/Santiago';

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

        console.error(`🚫 Error de CORS: El origen '${origin}' no está en la lista permitida.`);
        console.error(`Configuración actual: FRONTEND_URL=${process.env.FRONTEND_URL}, CORS_ORIGIN=${process.env.CORS_ORIGIN}`);

        return callback(new Error('Not allowed by CORS'));
    }
})); // Importante para evitar errores de bloqueo en el navegador
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

function getAdminTokenFromReq(req) {
    const headerToken = req.header('x-admin-token') || req.header('x-admin-manager-token') || '';
    if (headerToken) return headerToken;
    const auth = req.header('authorization') || '';
    const m = auth.match(/^Bearer\s+(.+)$/i);
    return m ? m[1] : '';
}

function safeEqualString(a, b) {
    if (typeof a !== 'string' || typeof b !== 'string') return false;
    if (a.length !== b.length) return false;
    try {
        return crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));
    } catch {
        return false;
    }
}

function getChileBusinessOpenNow() {
    const fmt = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/Santiago',
        weekday: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    });
    const parts = fmt.formatToParts(new Date());
    const out = {};
    for (const p of parts) out[p.type] = p.value;
    const weekday = out.weekday;
    const hour = parseInt(out.hour, 10);
    const minute = parseInt(out.minute, 10);
    const minutes = hour * 60 + minute;
    const start = 13 * 60 + 30;
    const end = (weekday === 'Fri' || weekday === 'Sat') ? (23 * 60 + 40) : (22 * 60 + 55);
    return minutes >= start && minutes <= end;
}

function normalizarSucursalKey(s) {
    const v = String(s || '').trim().toLowerCase();
    const key = v.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, '_');
    if (key === 'laserena' || key === 'la_serena' || key === 'la-serena') return 'la_serena';
    if (key === 'coquimbo') return 'coquimbo';
    return key || v;
}

function weekdayKeyFromShort(weekday) {
    switch (weekday) {
        case 'Mon': return 'mon';
        case 'Tue': return 'tue';
        case 'Wed': return 'wed';
        case 'Thu': return 'thu';
        case 'Fri': return 'fri';
        case 'Sat': return 'sat';
        case 'Sun': return 'sun';
        default: return null;
    }
}

function toMinuteSafe(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return null;
    if (n < 0 || n > 24 * 60) return null;
    return Math.trunc(n);
}

function getDayScheduleMinutes(row, weekdayShort) {
    const dayKey = weekdayKeyFromShort(weekdayShort);
    const horario = row?.horario_semanal;
    if (dayKey && horario && typeof horario === 'object' && horario[dayKey]) {
        const day = horario[dayKey];
        const o = toMinuteSafe(day?.open);
        const c = toMinuteSafe(day?.close);
        if (o === null || c === null) return { openMin: null, closeMin: null };
        return { openMin: o, closeMin: c };
    }
    const weekend = weekdayShort === 'Fri' || weekdayShort === 'Sat';
    const openMin = weekend ? toMinuteSafe(row?.open_weekend_min) : toMinuteSafe(row?.open_regular_min);
    const closeMin = weekend ? toMinuteSafe(row?.close_weekend_min) : toMinuteSafe(row?.close_regular_min);
    return { openMin, closeMin };
}

async function isSucursalOpen(sucursal) {
    try {
        const suc = normalizarSucursalKey(sucursal);
        const r = await pool.query('SELECT cerrado, horario_semanal, open_regular_min, close_regular_min, open_weekend_min, close_weekend_min FROM sucursales_config WHERE nombre = $1', [suc]);
        const row = r.rows[0];
        if (!row) return getChileBusinessOpenNow();
        const cerrado = row.cerrado === true;
        const { weekday, minutes } = getChileWeekdayAndMinutes();
        const { openMin, closeMin } = getDayScheduleMinutes(row, weekday);
        const inSchedule = openMin !== null && closeMin !== null && minutes >= openMin && minutes <= closeMin;
        return !cerrado && inSchedule;
    } catch {
        return getChileBusinessOpenNow();
    }
}

function requireOpenHours(req, res, next) {
    if (!getChileBusinessOpenNow()) {
        return res.status(403).json({ error: "Cerrado" });
    }
    return next();
}

app.use('/api/admin', (req, res, next) => {
    const expected = String(process.env.ADMIN_API_TOKEN || '');
    if (!expected) return next();
    const token = getAdminTokenFromReq(req);
    if (!token || !safeEqualString(token, expected)) {
        return res.status(401).json({ error: 'No autorizado' });
    }
    return next();
});

app.get('/api/admin/ping', (req, res) => {
    res.json({ ok: true });
});

// Borrar TODOS los pedidos (y sus detalles)
app.post('/api/admin/pedidos/reset', async (req, res) => {
    try {
        await pool.query("BEGIN");
        await pool.query("TRUNCATE TABLE detalle_pedidos, pedidos RESTART IDENTITY CASCADE");
        await pool.query("COMMIT");
        return res.json({ ok: true });
    } catch (err) {
        try { await pool.query("ROLLBACK"); } catch {}
        console.error("Error reseteando pedidos:", err?.message || err);
        return res.status(500).json({ error: "No se pudo borrar pedidos" });
    }
});

// Borrar un pedido específico por ID
app.delete('/api/admin/pedidos/:id', async (req, res) => {
    const { id } = req.params;
    try {
        await pool.query("BEGIN");
        await pool.query("DELETE FROM detalle_pedidos WHERE pedido_id = $1", [id]);
        const r = await pool.query("DELETE FROM pedidos WHERE id = $1", [id]);
        await pool.query("COMMIT");
        if (r.rowCount === 0) return res.status(404).json({ error: "Pedido no encontrado" });
        return res.json({ ok: true, id: Number(id) });
    } catch (err) {
        try { await pool.query("ROLLBACK"); } catch {}
        return res.status(500).json({ error: "No se pudo borrar el pedido" });
    }
});

// Borrar pedidos de un usuario por nombre
app.delete('/api/admin/pedidos/by-usuario', async (req, res) => {
    const nombre = (req.query.nombre || '').trim();
    if (!nombre) return res.status(400).json({ error: "Falta parámetro nombre" });
    try {
        await pool.query("BEGIN");
        const idsRes = await pool.query("SELECT id FROM pedidos WHERE usuario_nombre = $1", [nombre]);
        const ids = idsRes.rows.map(r => r.id);
        for (const pid of ids) {
            await pool.query("DELETE FROM detalle_pedidos WHERE pedido_id = $1", [pid]);
        }
        const r = await pool.query("DELETE FROM pedidos WHERE usuario_nombre = $1", [nombre]);
        await pool.query("COMMIT");
        return res.json({ ok: true, borrados: r.rowCount });
    } catch (err) {
        try { await pool.query("ROLLBACK"); } catch {}
        return res.status(500).json({ error: "No se pudo borrar pedidos del usuario" });
    }
});

app.get('/', (req, res) => {
    res.type('text/plain').send('API sitiolaserena OK. Prueba /api/health');
});

app.get('/api/health', (req, res) => {
    res.json({ ok: true });
});

function verifyTurnstile(responseToken, remoteIp) {
    const secret = process.env.TURNSTILE_SECRET_KEY;
    if (!secret) return Promise.resolve({ ok: true });
    if (!responseToken) return Promise.resolve({ ok: false });

    const body = new URLSearchParams();
    body.set('secret', secret);
    body.set('response', responseToken);
    if (remoteIp) body.set('remoteip', remoteIp);

    return new Promise((resolve) => {
        const req = https.request(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Content-Length': Buffer.byteLength(body.toString())
                }
            },
            (resp) => {
                let data = '';
                resp.on('data', (chunk) => (data += chunk));
                resp.on('end', () => {
                    try {
                        const json = JSON.parse(data);
                        resolve({ ok: Boolean(json && json.success), data: json });
                    } catch {
                        resolve({ ok: false });
                    }
                });
            }
        );
        req.on('error', () => resolve({ ok: false }));
        req.write(body.toString());
        req.end();
    });
}

app.get('/api/public-config', (req, res) => {
    res.json({ turnstileSiteKey: process.env.TURNSTILE_SITE_KEY || null });
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
    await pool.query(`ALTER TABLE productos ADD COLUMN IF NOT EXISTS mitades_disponible BOOLEAN NOT NULL DEFAULT TRUE`);
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

async function initSucursalConfig() {
    try {
        await pool.query(`
            CREATE TABLE IF NOT EXISTS sucursales_config (
                nombre TEXT PRIMARY KEY,
                demora_actual INTEGER NOT NULL DEFAULT 30,
                cerrado BOOLEAN NOT NULL DEFAULT FALSE,
                cerrado_origen TEXT NOT NULL DEFAULT 'auto',
                cerrado_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                horario_semanal JSONB NOT NULL DEFAULT '{}'::jsonb,
                open_regular_min INTEGER NOT NULL DEFAULT 810,
                close_regular_min INTEGER NOT NULL DEFAULT 1375,
                open_weekend_min INTEGER NOT NULL DEFAULT 810,
                close_weekend_min INTEGER NOT NULL DEFAULT 1420
            )
        `);
        await pool.query(`ALTER TABLE sucursales_config ADD COLUMN IF NOT EXISTS cerrado BOOLEAN NOT NULL DEFAULT FALSE`);
        await pool.query(`ALTER TABLE sucursales_config ADD COLUMN IF NOT EXISTS cerrado_origen TEXT NOT NULL DEFAULT 'auto'`);
        await pool.query(`ALTER TABLE sucursales_config ADD COLUMN IF NOT EXISTS cerrado_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`);
        await pool.query(`ALTER TABLE sucursales_config ADD COLUMN IF NOT EXISTS horario_semanal JSONB NOT NULL DEFAULT '{}'::jsonb`);
        await pool.query(`ALTER TABLE sucursales_config ADD COLUMN IF NOT EXISTS open_regular_min INTEGER NOT NULL DEFAULT 810`);
        await pool.query(`ALTER TABLE sucursales_config ADD COLUMN IF NOT EXISTS close_regular_min INTEGER NOT NULL DEFAULT 1375`);
        await pool.query(`ALTER TABLE sucursales_config ADD COLUMN IF NOT EXISTS open_weekend_min INTEGER NOT NULL DEFAULT 810`);
        await pool.query(`ALTER TABLE sucursales_config ADD COLUMN IF NOT EXISTS close_weekend_min INTEGER NOT NULL DEFAULT 1420`);
        const rows = await pool.query(`SELECT nombre FROM sucursales_config`);
        const existing = new Set(rows.rows.map(r => (r.nombre || '').toLowerCase()));
        if (!existing.has('la_serena')) {
            await pool.query(
                `INSERT INTO sucursales_config (nombre, demora_actual, cerrado, cerrado_origen, cerrado_updated_at, horario_semanal, open_regular_min, close_regular_min, open_weekend_min, close_weekend_min)
                 VALUES ($1, 30, FALSE, 'auto', NOW(),
                   '{"mon":{"open":810,"close":1375},"tue":{"open":810,"close":1375},"wed":{"open":810,"close":1375},"thu":{"open":810,"close":1375},"fri":{"open":810,"close":1420},"sat":{"open":810,"close":1420},"sun":{"open":810,"close":1375}}'::jsonb,
                   810, 1375, 810, 1420)`,
                ['la_serena']
            );
        }
        if (!existing.has('coquimbo')) {
            await pool.query(
                `INSERT INTO sucursales_config (nombre, demora_actual, cerrado, cerrado_origen, cerrado_updated_at, horario_semanal, open_regular_min, close_regular_min, open_weekend_min, close_weekend_min)
                 VALUES ($1, 30, FALSE, 'auto', NOW(),
                   '{"mon":{"open":810,"close":1375},"tue":{"open":810,"close":1375},"wed":{"open":810,"close":1375},"thu":{"open":810,"close":1375},"fri":{"open":810,"close":1420},"sat":{"open":810,"close":1420},"sun":{"open":810,"close":1375}}'::jsonb,
                   810, 1375, 810, 1420)`,
                ['coquimbo']
            );
        }
        await pool.query(`UPDATE sucursales_config SET cerrado_origen = 'auto' WHERE cerrado_origen IS NULL OR cerrado_origen = ''`);
        await pool.query(`UPDATE sucursales_config SET cerrado_updated_at = NOW() WHERE cerrado_updated_at IS NULL`);
        await pool.query(`
            UPDATE sucursales_config
            SET horario_semanal = jsonb_build_object(
                'mon', jsonb_build_object('open', open_regular_min, 'close', close_regular_min),
                'tue', jsonb_build_object('open', open_regular_min, 'close', close_regular_min),
                'wed', jsonb_build_object('open', open_regular_min, 'close', close_regular_min),
                'thu', jsonb_build_object('open', open_regular_min, 'close', close_regular_min),
                'fri', jsonb_build_object('open', open_weekend_min, 'close', close_weekend_min),
                'sat', jsonb_build_object('open', open_weekend_min, 'close', close_weekend_min),
                'sun', jsonb_build_object('open', open_regular_min, 'close', close_regular_min)
            )
            WHERE horario_semanal IS NULL OR horario_semanal = '{}'::jsonb
        `);
        console.log('✅ Sucursales_config OK');
    } catch (e) {
        console.error('Error inicializando sucursales_config:', e.message);
    }
}

initSucursalConfig();

function getChileWeekdayAndMinutes() {
    const fmt = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/Santiago',
        weekday: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    });
    const parts = fmt.formatToParts(new Date());
    const out = {};
    for (const p of parts) out[p.type] = p.value;
    const weekday = out.weekday;
    const hour = parseInt(out.hour, 10);
    const minute = parseInt(out.minute, 10);
    return { weekday, minutes: hour * 60 + minute };
}

async function syncAutoCierreSucursales() {
    try {
        const { weekday, minutes } = getChileWeekdayAndMinutes();
        const configs = await pool.query(`SELECT nombre, horario_semanal, open_regular_min, close_regular_min, open_weekend_min, close_weekend_min FROM sucursales_config`);
        for (const c of configs.rows) {
            const { openMin, closeMin } = getDayScheduleMinutes(c, weekday);
            const inSchedule = openMin !== null && closeMin !== null && minutes >= openMin && minutes <= closeMin;
            if (!inSchedule) {
                await pool.query(`UPDATE sucursales_config SET cerrado = TRUE, cerrado_origen = 'auto', cerrado_updated_at = NOW() WHERE nombre = $1`, [c.nombre]);
            } else if (minutes === openMin) {
                await pool.query(`UPDATE sucursales_config SET cerrado = FALSE, cerrado_origen = 'auto', cerrado_updated_at = NOW() WHERE nombre = $1`, [c.nombre]);
            } else {
                await pool.query(`UPDATE sucursales_config SET cerrado = FALSE, cerrado_origen = 'auto', cerrado_updated_at = NOW() WHERE nombre = $1 AND cerrado = TRUE AND cerrado_origen = 'auto'`, [c.nombre]);
            }
        }
    } catch (e) {
        console.error('Error syncAutoCierreSucursales:', e?.message || e);
    }
}

setInterval(syncAutoCierreSucursales, 30000);
syncAutoCierreSucursales();

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
    const { email, password, cartToken, turnstileToken } = req.body || {};
    try {
        const remoteIp = req.headers['cf-connecting-ip'] || req.headers['x-forwarded-for']?.toString().split(',')[0]?.trim() || req.socket?.remoteAddress;
        const turnstile = await verifyTurnstile(turnstileToken, remoteIp);
        if (!turnstile.ok) {
            return res.status(400).json({ error: "Verificación anti-robot fallida" });
        }

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

app.post('/api/admin/login', async (req, res) => {
    const { email, password } = req.body || {};
    const expected = String(process.env.ADMIN_API_TOKEN || '');
    if (!expected) {
        return res.status(500).json({ error: "ADMIN_API_TOKEN no configurado" });
    }
    const token = getAdminTokenFromReq(req);
    if (!token || !safeEqualString(token, expected)) {
        return res.status(401).json({ error: "No autorizado" });
    }
    try {
        if (!email || !password) {
            return res.json({
                mensaje: "Login exitoso",
                usuario: { nombre: "admin", telefono: "", rol: "admin" }
            });
        }
        const usuario = await pool.query("SELECT * FROM usuarios WHERE email = $1", [email]);
        if (usuario.rows.length === 0) {
            return res.status(400).json({ error: "Credenciales inválidas" });
        }
        const esValida = await bcrypt.compare(password, usuario.rows[0].password);
        if (!esValida) {
            return res.status(400).json({ error: "Credenciales inválidas" });
        }
        if (usuario.rows[0].rol !== 'admin') {
            return res.status(403).json({ error: "No tienes permiso" });
        }
        return res.json({
            mensaje: "Login exitoso",
            usuario: {
                nombre: usuario.rows[0].nombre,
                telefono: usuario.rows[0].telefono,
                rol: usuario.rows[0].rol
            }
        });
    } catch (err) {
        console.error(err.message);
        return res.status(500).json({ error: "Error en el servidor" });
    }
});

// --- RUTAS DE PEDIDOS (PARA PRODUCCIÓN) ---

// 4. Crear un nuevo pedido (carrito.html)
app.post('/api/pedidos', async (req, res) => {
    const { usuario, telefono, sucursal, productos, total } = req.body;
    try {
        const sucKey = normalizarSucursalKey(sucursal);
        if (!(await isSucursalOpen(sucKey))) {
            return res.status(403).json({ error: "Estimad@ cliente en este momento nos encontramos cerrado" });
        }
        // Obtener la demora actual configurada para esta sucursal
        const config = await pool.query("SELECT demora_actual FROM sucursales_config WHERE nombre = $1", [sucKey]);
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
        const pedido = await pool.query(
            "SELECT *, EXTRACT(EPOCH FROM fecha) * 1000 AS fecha_ms, to_char(fecha,'YYYY-MM-DD HH24:MI:SS') AS fecha_local FROM pedidos WHERE id = $1",
            [id]
        );
        if (pedido.rows.length === 0) {
            return res.status(404).json({ error: "Pedido no encontrado" });
        }
        
        const detalles = await pool.query("SELECT * FROM detalle_pedidos WHERE pedido_id = $1", [id]);
        
        res.json({
            pedido: { ...pedido.rows[0], fecha: pedido.rows[0].fecha_local },
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
            "SELECT *, EXTRACT(EPOCH FROM fecha) * 1000 AS fecha_ms, to_char(fecha,'YYYY-MM-DD HH24:MI:SS') AS fecha_local FROM pedidos WHERE usuario_nombre = $1 ORDER BY fecha DESC",
            [nombre]
        );
        
        // Para cada pedido, obtenemos sus detalles (usando Promise.all para eficiencia)
        const pedidosConDetalle = await Promise.all(pedidos.rows.map(async (p) => {
            const detalles = await pool.query("SELECT * FROM detalle_pedidos WHERE pedido_id = $1", [p.id]);
            return {
                ...p,
                fecha: p.fecha_local,
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
            query += " AND lower(replace(sucursal, ' ', '_')) = lower(replace($1, ' ', '_'))";
            params.push(String(sucursal));
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
        const sucKey = normalizarSucursalKey(sucursal);
        const resultado = await pool.query("SELECT * FROM sucursales_config WHERE nombre = $1", [sucKey]);
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
    const { demora_actual, cerrado, schedule, horario_semanal, open_regular, close_regular, open_weekend, close_weekend } = req.body || {};
    try {
        const expected = String(process.env.ADMIN_API_TOKEN || '');
        if (expected) {
            const token = getAdminTokenFromReq(req);
            if (!token || !safeEqualString(token, expected)) {
                return res.status(401).json({ error: "No autorizado" });
            }
        }
        const sucKey = normalizarSucursalKey(sucursal);
        const cur = await pool.query("SELECT demora_actual, cerrado, cerrado_origen, horario_semanal, open_regular_min, close_regular_min, open_weekend_min, close_weekend_min FROM sucursales_config WHERE nombre = $1", [sucKey]);

        function parseHHMM(s) {
            if (s === null || s === undefined) return null;
            const str = String(s).trim();
            if (!str) return null;
            const m = str.match(/^(\d{1,2}):(\d{2})$/);
            if (!m) return null;
            const hh = parseInt(m[1], 10);
            const mm = parseInt(m[2], 10);
            if (!Number.isFinite(hh) || !Number.isFinite(mm)) return null;
            if (hh < 0 || hh > 23) return null;
            if (mm < 0 || mm > 59) return null;
            return hh * 60 + mm;
        }

        function normalizeSchedule(obj) {
            if (!obj || typeof obj !== 'object') return null;
            const days = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
            const out = {};
            for (const d of days) {
                const raw = obj[d] || {};
                const openStr = raw.open ?? raw.apertura ?? raw.opening ?? null;
                const closeStr = raw.close ?? raw.cierre ?? raw.closing ?? null;
                const o = parseHHMM(openStr);
                const c = parseHHMM(closeStr);
                if ((openStr === null || openStr === undefined || String(openStr).trim() === '') && (closeStr === null || closeStr === undefined || String(closeStr).trim() === '')) {
                    out[d] = { open: null, close: null };
                    continue;
                }
                if (o === null || c === null) return null;
                if (o >= c) return null;
                out[d] = { open: o, close: c };
            }
            return out;
        }

        function scheduleFromLegacy(orMin, crMin, owMin, cwMin) {
            const regOpen = orMin ?? 810;
            const regClose = crMin ?? 1375;
            const weOpen = owMin ?? 810;
            const weClose = cwMin ?? 1420;
            return {
                mon: { open: regOpen, close: regClose },
                tue: { open: regOpen, close: regClose },
                wed: { open: regOpen, close: regClose },
                thu: { open: regOpen, close: regClose },
                fri: { open: weOpen, close: weClose },
                sat: { open: weOpen, close: weClose },
                sun: { open: regOpen, close: regClose }
            };
        }

        const scheduleInput = schedule || horario_semanal;
        const scheduleNorm = normalizeSchedule(scheduleInput);
        const legacyOr = parseHHMM(open_regular);
        const legacyCr = parseHHMM(close_regular);
        const legacyOw = parseHHMM(open_weekend);
        const legacyCw = parseHHMM(close_weekend);

        const hasScheduleInput = scheduleInput && typeof scheduleInput === 'object';
        if (hasScheduleInput && !scheduleNorm) {
            return res.status(400).json({ error: "Horario inválido" });
        }
        function isBadTimeStr(raw, parsed) {
            if (raw === null || raw === undefined) return false;
            const s = String(raw).trim();
            if (!s) return false;
            return parsed === null;
        }
        if (isBadTimeStr(open_regular, legacyOr) || isBadTimeStr(close_regular, legacyCr) || isBadTimeStr(open_weekend, legacyOw) || isBadTimeStr(close_weekend, legacyCw)) {
            return res.status(400).json({ error: "Formato de hora inválido (HH:MM)" });
        }
        if (cur.rows.length === 0) {
            const dem = typeof demora_actual === 'number' ? demora_actual : 30;
            const cer = typeof cerrado === 'boolean' ? cerrado : false;
            const origen = typeof cerrado === 'boolean' ? 'manual' : 'auto';
            const sch = scheduleNorm || scheduleFromLegacy(legacyOr, legacyCr, legacyOw, legacyCw);
            const values = {
                open_regular_min: sch.mon.open ?? 810,
                close_regular_min: sch.mon.close ?? 1375,
                open_weekend_min: sch.fri.open ?? 810,
                close_weekend_min: sch.fri.close ?? 1420
            };
            await pool.query(
                "INSERT INTO sucursales_config (nombre, demora_actual, cerrado, cerrado_origen, cerrado_updated_at, horario_semanal, open_regular_min, close_regular_min, open_weekend_min, close_weekend_min) VALUES ($1, $2, $3, $4, NOW(), $5::jsonb, $6, $7, $8, $9)",
                [sucKey, dem, cer, origen, JSON.stringify(sch), values.open_regular_min, values.close_regular_min, values.open_weekend_min, values.close_weekend_min]
            );
            return res.json({ mensaje: "Configuración creada", demora_actual: dem, cerrado: cer, cerrado_origen: origen });
        }
        const dem = typeof demora_actual === 'number' ? demora_actual : cur.rows[0].demora_actual;
        const cer = typeof cerrado === 'boolean' ? cerrado : cur.rows[0].cerrado;
        const origen = typeof cerrado === 'boolean' ? 'manual' : cur.rows[0].cerrado_origen;
        const currentSchedule = normalizeSchedule(cur.rows[0].horario_semanal) || scheduleFromLegacy(cur.rows[0].open_regular_min, cur.rows[0].close_regular_min, cur.rows[0].open_weekend_min, cur.rows[0].close_weekend_min);
        const sch = scheduleNorm || (legacyOr !== null || legacyCr !== null || legacyOw !== null || legacyCw !== null ? scheduleFromLegacy(legacyOr, legacyCr, legacyOw, legacyCw) : currentSchedule);
        const nr = {
            open_regular_min: sch.mon.open ?? cur.rows[0].open_regular_min,
            close_regular_min: sch.mon.close ?? cur.rows[0].close_regular_min,
            open_weekend_min: sch.fri.open ?? cur.rows[0].open_weekend_min,
            close_weekend_min: sch.fri.close ?? cur.rows[0].close_weekend_min
        };
        await pool.query(
            "UPDATE sucursales_config SET demora_actual = $1, cerrado = $2, cerrado_origen = $3, cerrado_updated_at = NOW(), horario_semanal = $4::jsonb, open_regular_min = $5, close_regular_min = $6, open_weekend_min = $7, close_weekend_min = $8 WHERE nombre = $9",
            [dem, cer, origen, JSON.stringify(sch), nr.open_regular_min, nr.close_regular_min, nr.open_weekend_min, nr.close_weekend_min, sucKey]
        );
        res.json({ mensaje: "Configuración actualizada", demora_actual: dem, cerrado: cer, cerrado_origen: origen });
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
    const { nombre, precio, categoria, sucursal, descripcion, disponible, combo2_disponible, mitades_disponible } = req.body;
    try {
        const combo2Value = combo2_disponible === undefined ? null : combo2_disponible;
        const mitadesValue = mitades_disponible === undefined ? null : mitades_disponible;
        const nuevo = await pool.query(
            "INSERT INTO productos (nombre, precio, categoria, sucursal, descripcion, disponible, combo2_disponible, mitades_disponible) VALUES ($1, $2, $3, $4, $5, $6, COALESCE($7, TRUE), COALESCE($8, TRUE)) RETURNING *",
            [nombre, precio, categoria, sucursal, descripcion, disponible, combo2Value, mitadesValue]
        );
        res.json(nuevo.rows[0]);
    } catch (err) {
        res.status(500).json({ error: "Error al crear producto" });
    }
});

app.put('/api/admin/productos/:id', async (req, res) => {
    const { id } = req.params;
    const { nombre, precio, categoria, sucursal, descripcion, disponible, combo2_disponible, mitades_disponible } = req.body;
    try {
        const combo2Value = combo2_disponible === undefined ? null : combo2_disponible;
        const mitadesValue = mitades_disponible === undefined ? null : mitades_disponible;
        const actualizado = await pool.query(
            "UPDATE productos SET nombre=$1, precio=$2, categoria=$3, sucursal=$4, descripcion=$5, disponible=$6, combo2_disponible=COALESCE($7, combo2_disponible), mitades_disponible=COALESCE($8, mitades_disponible) WHERE id=$9 RETURNING *",
            [nombre, precio, categoria, sucursal, descripcion, disponible, combo2Value, mitadesValue, id]
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
        let sucursalForOpen = null;
        const pedidoId = parseInt(String(ordenId || ''), 10);
        if (!Number.isNaN(pedidoId)) {
            try {
                const pr = await pool.query('SELECT sucursal FROM pedidos WHERE id = $1', [pedidoId]);
                sucursalForOpen = pr.rows[0]?.sucursal || null;
            } catch {}
        }
        const allow = sucursalForOpen ? (await isSucursalOpen(sucursalForOpen)) : getChileBusinessOpenNow();
        if (!allow) return res.status(403).json({ error: "Estimad@ cliente en este momento nos encontramos cerrado" });
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
