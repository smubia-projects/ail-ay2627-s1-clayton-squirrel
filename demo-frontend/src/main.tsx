import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { ErrorBoundary } from './components/ErrorBoundary.tsx'
import { QuotaModals } from './components/QuotaModals.tsx'
import { ToastProvider } from './components/ToastProvider.tsx'
import { Root } from './Root.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <ToastProvider>
        <Root />
        <QuotaModals />
      </ToastProvider>
    </ErrorBoundary>
  </StrictMode>,
)
