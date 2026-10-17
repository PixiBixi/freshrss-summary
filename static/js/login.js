(function () {
  const L = {
    fr: { title: 'Connexion', subtitle: 'Session requise pour modifier tes articles.', username: 'Identifiant', password: 'Mot de passe', submit: 'Se connecter', signingIn: 'Connexion…', failed: 'Échec', show: 'Afficher', hide: 'Masquer', readonly: 'Continuer en lecture seule', pitchTitle: 'Le triage de tes flux, triés par burn rate.', pitchText: 'Les non-lus FreshRSS scorés sur tes topics. Connecte-toi pour ack, bookmark et snoozer.', foot: 'Lecture seule possible sans compte.' },
    en: { title: 'Sign in', subtitle: 'Sign-in required to edit your articles.', username: 'Username', password: 'Password', submit: 'Sign in', signingIn: 'Signing in…', failed: 'Failed', show: 'Show', hide: 'Hide', readonly: 'Continue read-only', pitchTitle: 'Your feed triage, sorted by burn rate.', pitchText: 'Unread FreshRSS items scored against your topics. Sign in to ack, bookmark and snooze.', foot: 'Read-only access is available without an account.' },
    de: { title: 'Anmelden', subtitle: 'Anmeldung erforderlich, um Artikel zu bearbeiten.', username: 'Benutzername', password: 'Passwort', submit: 'Anmelden', signingIn: 'Anmeldung…', failed: 'Fehler', show: 'Anzeigen', hide: 'Verbergen', readonly: 'Schreibgeschützt fortfahren', pitchText: 'Ungelesene FreshRSS-Artikel, nach deinen Themen bewertet. Melde dich an, um zu bestätigen, zu merken und zurückzustellen.', pitchTitle: 'Dein Feed-Triage, sortiert nach Burn Rate.', foot: 'Schreibgeschützter Zugriff ist ohne Konto möglich.' },
    es: { title: 'Iniciar sesión', subtitle: 'Sesión requerida para modificar tus artículos.', username: 'Usuario', password: 'Contraseña', submit: 'Iniciar sesión', signingIn: 'Conectando…', failed: 'Error', show: 'Mostrar', hide: 'Ocultar', readonly: 'Continuar en solo lectura', pitchTitle: 'El triaje de tus feeds, ordenado por burn rate.', pitchText: 'Los no leídos de FreshRSS puntuados según tus temas. Inicia sesión para confirmar, guardar y posponer.', foot: 'Se puede acceder en solo lectura sin cuenta.' },
    it: { title: 'Accedi', subtitle: 'Accesso richiesto per modificare i tuoi articoli.', username: 'Nome utente', password: 'Password', submit: 'Accedi', signingIn: 'Accesso…', failed: 'Errore', show: 'Mostra', hide: 'Nascondi', readonly: 'Continua in sola lettura', pitchTitle: 'Il triage dei tuoi feed, ordinato per burn rate.', pitchText: 'I non letti di FreshRSS valutati sui tuoi topic. Accedi per confermare, salvare e posticipare.', foot: 'La sola lettura è possibile senza account.' },
    pt: { title: 'Entrar', subtitle: 'Sessão necessária para modificar os teus artigos.', username: 'Utilizador', password: 'Palavra-passe', submit: 'Entrar', signingIn: 'A entrar…', failed: 'Falha', show: 'Mostrar', hide: 'Ocultar', readonly: 'Continuar em modo só de leitura', pitchTitle: 'A triagem dos teus feeds, ordenada por burn rate.', pitchText: 'Os não lidos do FreshRSS pontuados pelos teus tópicos. Entra para confirmar, guardar e adiar.', foot: 'O modo só de leitura está disponível sem conta.' },
  };
  let saved = null;
  try { saved = localStorage.getItem('freshrss-lang'); } catch (e) {}
  const nav  = (navigator.language || '').toLowerCase().slice(0, 2);
  const lang = (saved && L[saved]) ? saved : (L[nav] ? nav : 'fr');
  const d = L[lang];
  const $ = (id) => document.getElementById(id);
  const set = (id, text) => { const el = $(id); if (el) el.textContent = text; };

  document.documentElement.lang = lang;
  set('login-title', d.title);
  set('login-subtitle', d.subtitle);
  set('login-username-label', d.username);
  set('login-password-label', d.password);
  set('login-submit-btn', d.submit);
  set('login-err-label', d.failed);
  set('login-show', d.show);
  set('login-readonly', d.readonly);
  set('login-pitch-title', d.pitchTitle);
  set('login-pitch-text', d.pitchText);
  set('login-foot', d.foot);

  const pw = $('password'), toggle = $('login-show');
  toggle.addEventListener('click', function () {
    const reveal = pw.type === 'password';
    pw.type = reveal ? 'text' : 'password';
    toggle.textContent = reveal ? d.hide : d.show;
    toggle.setAttribute('aria-pressed', String(reveal));
  });

  // No preventDefault: the native POST proceeds, the spinner only gives feedback.
  $('login-form').addEventListener('submit', function (e) {
    if (!e.target.checkValidity()) return;
    const btn = $('login-submit-btn');
    btn.innerHTML = '<span class="spin"></span>';
    btn.appendChild(document.createTextNode(d.signingIn));
    setTimeout(function () { btn.disabled = true; }, 0);
  });
})();
