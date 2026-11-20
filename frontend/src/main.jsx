import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import { Wallpaper } from './components/ui.jsx';
import { AuthProvider } from './hooks/useAuth.jsx';
import { installSpecularHighlights } from './hooks/useSpecular.js';
import './styles.css';

installSpecularHighlights();

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Wallpaper />
    <AuthProvider>
      <App />
    </AuthProvider>
  </React.StrictMode>,
);
