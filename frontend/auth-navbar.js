/**
 * auth-navbar.js
 * Centraliza la lógica de la barra de navegación para mostrar 
 * el estado de autenticación (Login/Registro o Saludo de Usuario).
 */

function actualizarNavbar() {
    const authContainer = document.getElementById('navbar-auth');
    if (!authContainer) return;

    const cartToken = asegurarCartToken();

    // 1. Obtener datos del localStorage
    const nombreUsuario = localStorage.getItem('usuario_nombre');
    
    // 2. Obtener el carrito para mostrar la cantidad real
    const carrito = JSON.parse(localStorage.getItem('carrito')) || [];
    const cantidad = carrito.length;

    // 3. Construir el HTML base (Carrito siempre visible)
    let menuHTML = `
        <a href="carrito.html" class="cart-link">
            <i class="fas fa-shopping-cart"></i> 
            <span>Carrito (<span id="cart-count">${cantidad}</span>)</span>
        </a>
    `;
    // 4. Lógica de visibilidad según el estado de la sesión
    if (nombreUsuario && nombreUsuario !== "null" && nombreUsuario !== "undefined") {
        // SI ESTÁ LOGUEADO: Solo mostramos el saludo y el botón de salir
        menuHTML += `
            <a href="mipedido.html" class="my-order-link">
                <i class="fas fa-receipt"></i> Mi Pedido
            </a>
            <span style="color: #FFD700; font-weight: bold; margin-left: 15px;">
                🍕 Hola, ${nombreUsuario}
            </span>
            <a href="#" id="btn-cerrar-sesion" style="font-size: 0.8rem; color: #ff4d4d; margin-left: 10px; text-decoration: underline;">
                (Salir)
            </a>
        `;
    } else {
        // SI NO ESTÁ LOGUEADO: Mostramos los botones de acceso
        menuHTML += `
            <a href="login.html">Iniciar Sesión</a>
            <a href="registro.html" class="btn-registro">Crear Cuenta</a>
        `;
    }

    // 5. Inyectar al Navbar
    authContainer.innerHTML = menuHTML;

    guardarCarritoTemporal(cartToken, carrito);

    // 6. Configurar evento de cerrar sesión
    const btnSalir = document.getElementById('btn-cerrar-sesion');
    if (btnSalir) {
        btnSalir.addEventListener('click', (e) => {
            e.preventDefault();
            // Limpiar datos de usuario y también el carrito para que el nuevo usuario empiece de cero
            localStorage.removeItem('usuario_nombre');
            localStorage.removeItem('auth_token');
            localStorage.removeItem('carrito'); 
            window.location.reload(); 
        });
    }
}

function asegurarCartToken() {
    let token = localStorage.getItem('cart_token');
    if (!token) {
        token = `cart_${Date.now()}_${Math.random().toString(16).slice(2)}`;
        localStorage.setItem('cart_token', token);
    }
    return token;
}

async function guardarCarritoTemporal(cartToken, carrito) {
    try {
        const baseUrl = (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) ? window.APP_CONFIG.API_BASE_URL : 'http://localhost:3000';
        await fetch(`${baseUrl}/api/carrito/guardar`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cartToken, carrito })
        });
    } catch (e) {
    }
}

// Ejecutar cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', actualizarNavbar);
