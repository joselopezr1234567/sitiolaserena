async function pagarCarritoConWebpay(sucursal, usuario, telefono) {
  try {
    const baseUrl = (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) ? window.APP_CONFIG.API_BASE_URL : 'http://localhost:3000';
    const carrito = JSON.parse(localStorage.getItem('carrito') || '[]');
    if (!carrito.length) {
      window.location.href = 'carrito.html';
      return;
    }
    const total = carrito.reduce((acc, it) => acc + (parseInt(it.precio, 10) || 0), 0);

    const resPedido = await fetch(`${baseUrl}/api/pedidos`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        usuario,
        telefono,
        sucursal,
        productos: carrito.map(it => ({
          nombre: it.nombre || it.producto_nombre || 'Producto',
          precio: parseInt(it.precio, 10) || 0,
          detalles: it.detalles || ''
        })),
        total
      })
    });
    if (!resPedido.ok) {
      return;
    }
    const { pedidoId } = await resPedido.json();

    const resPago = await fetch(`${baseUrl}/api/pagos/crear`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        monto: total,
        ordenId: pedidoId
      })
    });
    if (!resPago.ok) {
      return;
    }
    const datos = await resPago.json();
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = datos.url;
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'token_ws';
    input.value = datos.token;
    form.appendChild(input);
    document.body.appendChild(form);

    // Limpiamos carrito antes de enviar (el backend guardó la orden)
    localStorage.removeItem('carrito');
    form.submit();
  } catch (e) {
    console.error('Error al pagar:', e);
  }
}
