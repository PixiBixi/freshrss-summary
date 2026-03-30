(function () {
  const L = {
    fr: { subtitle: 'Connexion requise',              username: 'Identifiant',    password: 'Mot de passe',   submit: 'Se connecter' },
    en: { subtitle: 'Authentication required',        username: 'Username',       password: 'Password',       submit: 'Sign in' },
    de: { subtitle: 'Authentifizierung erforderlich', username: 'Benutzername',   password: 'Passwort',       submit: 'Anmelden' },
    es: { subtitle: 'Autenticación requerida',        username: 'Usuario',        password: 'Contraseña',     submit: 'Iniciar sesión' },
    it: { subtitle: 'Autenticazione richiesta',       username: 'Nome utente',    password: 'Password',       submit: 'Accedi' },
    pt: { subtitle: 'Autenticação necessária',        username: 'Utilizador',     password: 'Palavra-passe',  submit: 'Entrar' },
  };
  const saved = localStorage.getItem('freshrss-lang');
  const nav   = (navigator.language || '').toLowerCase().slice(0, 2);
  const lang  = (saved && L[saved]) ? saved : (L[nav] ? nav : 'fr');
  const d = L[lang];
  document.getElementById('login-subtitle').textContent       = d.subtitle;
  document.getElementById('login-username-label').textContent = d.username;
  document.getElementById('login-password-label').textContent = d.password;
  document.getElementById('login-submit-btn').textContent     = d.submit;
})();
