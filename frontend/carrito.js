// Ejemplo de datos basados en tu imagen
const listaPrecios = {
    "Pizzas Familiares": [
        { nombre: "Pepperoni", precio: 5000 },
        { nombre: "Queso Orégano", precio: 5000 },
        { nombre: "Oliva", precio: 7000 }
    ],
    "Bebidas": [
        { nombre: "Pepsi 350cc", precio: 1500 },
        { nombre: "Pepsi 2 Litros", precio: 3500 }
    ]
};

let carrito = JSON.parse(localStorage.getItem('carrito')) || [];

// Función para abrir el modal y cargar opciones
function abrirModal(categoria) {
    const modal = document.getElementById('modal-pedido');
    const contenedor = document.getElementById('opciones-dinamicas');
    document.getElementById('modal-titulo').innerText = categoria;
    
    contenedor.innerHTML = ""; // Limpiar
    
    const opciones = listaPrecios[categoria];
    opciones.forEach(item => {
        contenedor.innerHTML += `
            <div class="opciones-grupo">
                <input type="radio" name="item-seleccionado" value="${item.precio}" data-nombre="${item.nombre}">
                ${item.nombre} - $${item.precio.toLocaleString()}
            </div>
        `;
    });
    
    modal.style.display = "block";
}

function volverASucursal() {
    // Intentamos obtener la última sucursal guardada
    const ultimaPagina = localStorage.getItem('ultima_sucursal');
    
    if (ultimaPagina) {
        // Si existe, redirige a esa página (La Serena o Coquimbo)
        window.location.href = ultimaPagina;
    } else {
        // Por si acaso no hay nada guardado, vuelve al index por defecto
        window.location.href = 'index.html';
    }
}

// Lógica para guardar en el carrito
document.getElementById('add-to-cart').addEventListener('click', () => {
    const seleccionado = document.querySelector('input[name="item-seleccionado"]:checked');
    if (seleccionado) {
        const item = {
            nombre: seleccionado.getAttribute('data-nombre'),
            precio: parseInt(seleccionado.value)
        };
        carrito.push(item);
        localStorage.setItem('carrito', JSON.stringify(carrito));
        document.getElementById('modal-pedido').style.display = "none";
    }
});
