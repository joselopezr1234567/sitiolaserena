async function pagarCarritoConWebpay(sucursal, usuario, telefono) {
  try {
    const baseUrl = (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) ? window.APP_CONFIG.API_BASE_URL : 'http://localhost:3000';
    const carrito = JSON.parse(localStorage.getItem('carrito') || '[]');
    if (!carrito.length) {
      window.location.href = 'carrito.html';
      return;
    }
    const overlay = document.createElement('div');
    overlay.style.position = 'fixed';
    overlay.style.inset = '0';
    overlay.style.background = 'rgba(0,0,0,0.75)';
    overlay.style.display = 'flex';
    overlay.style.alignItems = 'center';
    overlay.style.justifyContent = 'center';
    overlay.style.zIndex = '9999';
    overlay.innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;gap:12px">
        <div style="width:56px;height:56px;border:6px solid #fff;border-top-color:#ff0000;border-radius:50%;animation:spin 1s linear infinite"></div>
        <div style="color:#fff;font-family:Arial,Helvetica,sans-serif;font-weight:bold">Redirigiendo a Webpay...</div>
      </div>
      <style>@keyframes spin { to { transform: rotate(360deg); } }</style>
    `;
    document.body.appendChild(overlay);

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
      const msg = await resPedido.text().catch(() => '');
      overlay.remove();
      alert(`No se pudo crear el pedido.\n${msg || 'Intenta nuevamente.'}`);
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
      const msg = await resPago.text().catch(() => '');
      overlay.remove();
      alert(`No se pudo iniciar el pago.\n${msg || 'Intenta nuevamente.'}`);
      return;
    }
    const datos = await resPago.json();
    try {
      localStorage.setItem('last_webpay_token', String(datos.token || ''));
      localStorage.setItem('last_webpay_buyOrder', String(datos.buyOrder || pedidoId || ''));
      localStorage.setItem('last_webpay_url', String(datos.url || ''));
    } catch (e) {}
    if (!datos || !datos.url || !datos.token) {
      overlay.remove();
      alert('No se pudo iniciar el pago (respuesta inválida).');
      return;
    }
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
    try {
      const el = document.querySelector('body > div[style*="z-index: 9999"]');
      if (el) el.remove();
    } catch (e2) {}
    console.error('Error al pagar:', e);
    alert('Error al iniciar el pago. Revisa tu conexión e intenta nuevamente.');
  }
}
