import type { ButtonHTMLAttributes } from 'react'

const STYLES = {
  primary: 'bg-sky-600 text-white hover:bg-sky-500 disabled:bg-slate-800 disabled:text-slate-500',
  ghost: 'border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:text-slate-600 disabled:hover:bg-transparent',
  danger: 'bg-rose-600 text-white hover:bg-rose-500 disabled:bg-slate-800 disabled:text-slate-500',
}

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof STYLES }

export function Button({ variant = 'ghost', className = '', ...props }: Props) {
  return (
    <button
      type="button"
      className={`rounded px-2.5 py-1 text-xs font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed ${STYLES[variant]} ${className}`}
      {...props}
    />
  )
}

export function Spinner() {
  return <span className="inline-block size-3 animate-spin rounded-full border-2 border-sky-400 border-t-transparent" />
}
