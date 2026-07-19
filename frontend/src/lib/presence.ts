import { Coffee, Droplet, Smile, Users, Utensils, type LucideIcon } from "lucide-react";
import bathroomUrl from "@/assets/mascot/bathroom.svg";
import breakUrl from "@/assets/mascot/break.svg";
import helloUrl from "@/assets/mascot/hello.svg";
import lunchUrl from "@/assets/mascot/lunch.svg";
import meetingUrl from "@/assets/mascot/meeting.svg";

export type PresenceStatus =
  | "disponible"
  | "almorzando"
  | "en_el_bano"
  | "en_break"
  | "en_reunion";

export interface PresenceMetadata {
  label: string;
  icon: LucideIcon;
  art: string;
  tint: string;
  dotClass: string;
}

export const PRESENCE_CATALOG: Record<PresenceStatus, PresenceMetadata> = {
  disponible: { label: "Disponible", icon: Smile, art: helloUrl, tint: "bg-p-success/10 text-p-success", dotClass: "bg-p-success" },
  almorzando: { label: "Almorzando", icon: Utensils, art: lunchUrl, tint: "bg-p-accent-mid/15 text-p-accent-mid", dotClass: "bg-p-accent-mid" },
  en_el_bano: { label: "En el baño", icon: Droplet, art: bathroomUrl, tint: "bg-sky-100 text-sky-700", dotClass: "bg-sky-500" },
  en_break: { label: "En break", icon: Coffee, art: breakUrl, tint: "bg-amber-100 text-amber-700", dotClass: "bg-amber-500" },
  en_reunion: { label: "En reunión", icon: Users, art: meetingUrl, tint: "bg-p-accent-soft text-p-accent", dotClass: "bg-p-accent" },
};

export const PRESENCE_ORDER: PresenceStatus[] = ["disponible", "almorzando", "en_el_bano", "en_break", "en_reunion"];

export function presenceTimeAgo(iso: string | null): string {
  if (!iso) return "ahora";
  const elapsed = Math.max(0, Date.now() - new Date(iso).getTime());
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return "ahora";
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  const days = Math.floor(hours / 24);
  return `hace ${days} d`;
}
