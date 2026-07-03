// Copy to config.js and fill in for each environment. config.js is git-ignored.
// index.html loads config.js BEFORE the app, exposing these as
// window.SAMVARA_CONFIG.
//
// apiBaseUrl : where your API server lives. Either "https://host" or
//              "https://host/v1" works. Leave "" to use the page's own origin
//              (only useful if you serve the API and frontend together).
//
// There is deliberately NO token here. Signing in goes through the server-side
// email OTP flow (/v1/auth/send-code → /v1/auth/verify-code); the resulting
// session token lives in localStorage, never in a shipped file. The static
// API_TOKEN is used only by the GitHub Actions tick and must never appear in
// this file.
window.SAMVARA_CONFIG = {
  apiBaseUrl: "https://your-api-host.example.com",
};
