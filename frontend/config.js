window.APP_CONFIG = {
    API_BASE_URL: (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
        ? 'http://localhost:3000'
        : 'https://TU_BACKEND_RENDER.onrender.com'
};
