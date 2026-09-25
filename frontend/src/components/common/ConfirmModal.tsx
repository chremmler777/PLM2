/**
 * ConfirmModal: the older prop names (isOpen, message, confirmText,
 * isDangerous, isLoading, onCancel) over the shared ConfirmDialog.
 * New code should import ConfirmDialog directly.
 *
 * The parent closes it (as before): a confirm does not close it by itself,
 * but a rejected promise from onConfirm shows the backend reason inline.
 */
import ConfirmDialog from './ConfirmDialog'

interface Props {
  isOpen: boolean
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  onConfirm: () => void | Promise<void>
  onCancel: () => void
  isDangerous?: boolean
  isLoading?: boolean
}

export default function ConfirmModal({
  isOpen, title, message, confirmText = 'Confirm', cancelText = 'Cancel',
  onConfirm, onCancel, isDangerous = false, isLoading = false,
}: Props) {
  return (
    <ConfirmDialog open={isOpen} title={title} body={message} confirmLabel={confirmText}
      cancelLabel={cancelText} danger={isDangerous} pending={isLoading}
      onConfirm={onConfirm} onClose={onCancel} closeOnConfirm={false} />
  )
}
