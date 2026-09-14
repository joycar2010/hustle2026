import { RouterProvider } from 'react-router-dom'
import { router } from './router'
import { Toaster } from '@/components/ui/toast'
import { ConfirmHost } from '@/components/ui/confirm'
import { ErrorBoundary } from '@/components/ErrorBoundary'

function App() {
  return (
    <ErrorBoundary>
      <RouterProvider router={router} />
      <Toaster />
      <ConfirmHost />
    </ErrorBoundary>
  )
}

export default App
