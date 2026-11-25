export function RecoveryCodeList({ codes, saved, onSaved }: { codes: string[]; saved: boolean; onSaved: (saved: boolean) => void }) {
  return <>
    <ul aria-label="Recovery codes" className="grid grid-cols-2 gap-2 rounded-md border border-border bg-background p-3 text-center font-mono text-sm">
      {codes.map((code) => <li className="select-all" key={code}>{code}</li>)}
    </ul>
    <label className="flex items-start gap-2 text-sm">
      <input type="checkbox" className="mt-1 size-4 shrink-0 accent-primary" checked={saved} onChange={({ target }) => onSaved(target.checked)} />
      I’ve saved my recovery codes.
    </label>
  </>;
}
