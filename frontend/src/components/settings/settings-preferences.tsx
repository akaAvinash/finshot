import type { FormEvent, ReactNode, Ref } from "react";
import { Bell, Moon, Monitor, Sun, UserRound, type LucideIcon } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { workspaceTimezones, type NotificationPreferences, type SettingsCommand, type SettingsSnapshot } from "@/lib/api/workspace-controls-types";
import { maxDisplayName, timezoneLabels } from "@/lib/workspace-controls";

export function SettingsCard({ id, title, description, icon: Icon, children }: {
  id: string;
  title: string;
  description: string;
  icon: LucideIcon;
  children: ReactNode;
}) {
  return <Card aria-labelledby={id} className="scroll-mt-20 p-4 sm:p-5">
    <h2 id={id} tabIndex={-1} className="flex items-center gap-2 font-semibold tracking-tight"><Icon aria-hidden className="size-4 shrink-0 text-accent-foreground" /> {title}</h2>
    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description}</p>
    <div className="mt-4">{children}</div>
  </Card>;
}

const selectClass = "h-11 w-full min-w-0 rounded-lg border border-input bg-background px-3 text-base sm:text-sm";
const themes = [{ value: "light", label: "Light", icon: Sun }, { value: "dark", label: "Dark", icon: Moon }, { value: "system", label: "System", icon: Monitor }] as const;

export function ProfilePreferences({ snapshot, disabled, displayNameRef, onSave }: {
  snapshot: SettingsSnapshot;
  disabled: boolean;
  displayNameRef: Ref<HTMLInputElement>;
  onSave: (command: Extract<SettingsCommand, { kind: "set-profile" }>) => void;
}) {
  const { theme, setTheme } = useTheme();

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const timezone = workspaceTimezones.find((value) => value === fields.get("timezone"));
    if (timezone) onSave({ kind: "set-profile", displayName: String(fields.get("displayName") ?? ""), timezone });
  }

  return <SettingsCard id="profile-preferences" title="Profile and appearance" description="Use a sample display name, and choose the timezone for Alerts and Settings." icon={UserRound}>
    <form onSubmit={save}>
      <fieldset disabled={disabled} className="space-y-3">
        <div className="space-y-1.5"><Label htmlFor="settings-display-name">Demo display name</Label>
          <Input ref={displayNameRef} id="settings-display-name" name="displayName" defaultValue={snapshot.displayName} maxLength={maxDisplayName} required />
        </div>
        <div className="space-y-1.5"><Label htmlFor="settings-timezone">Timezone</Label>
          <select id="settings-timezone" name="timezone" defaultValue={snapshot.timezone} className={selectClass}>
            {workspaceTimezones.map((timezone) => <option key={timezone} value={timezone}>{timezoneLabels[timezone]}</option>)}
          </select>
        </div>
        <Button type="submit" variant="outline" className="h-11">Save profile</Button>
      </fieldset>
    </form>
    <div className="mt-4 border-t border-border pt-4">
      <p id="settings-theme-label" className="text-sm font-medium">Theme</p>
      <div role="group" aria-labelledby="settings-theme-label" className="mt-2 flex flex-wrap gap-2">
        {themes.map(({ value, label, icon: Icon }) => <Button key={value} variant={theme === value ? "default" : "outline"} className="h-11" aria-pressed={theme === value} onClick={() => setTheme(value)}>
          <Icon aria-hidden />{label}
        </Button>)}
      </div>
    </div>
  </SettingsCard>;
}

const notificationOptions = [
  { key: "inAppUpdates", label: "Optional in-app updates", description: "Save a preference for noncritical activity updates." },
  { key: "emailDigest", label: "Email digest", description: "Record a sample digest preference." },
  { key: "criticalSms", label: "Critical SMS", description: "Record a sample preference for critical notices only." },
] as const;

export function NotificationSettings({ values, disabled, onSave }: {
  values: NotificationPreferences;
  disabled: boolean;
  onSave: (command: Extract<SettingsCommand, { kind: "set-notifications" }>) => void;
}) {
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    onSave({ kind: "set-notifications", notifications: {
      inAppUpdates: fields.has("inAppUpdates"), emailDigest: fields.has("emailDigest"), criticalSms: fields.has("criticalSms"),
    } });
  }

  return <SettingsCard id="notification-preferences" title="Notifications" description="Critical in-app alerts always appear. The preview sends no email or SMS." icon={Bell}>
    <form onSubmit={save}>
      <fieldset disabled={disabled} className="space-y-3">
        {notificationOptions.map(({ key, label, description }) => <label key={key} className="flex cursor-pointer items-center gap-3 rounded-lg border border-border bg-background/45 p-3">
          <input type="checkbox" name={key} defaultChecked={values[key]} className="size-4 shrink-0 accent-primary" aria-label={label} />
          <span className="min-w-0"><span className="block text-sm font-medium">{label}</span><span className="mt-1 block text-xs text-muted-foreground">{description}</span></span>
        </label>)}
        <Button type="submit" variant="outline" className="h-11">Save notifications</Button>
      </fieldset>
    </form>
  </SettingsCard>;
}
