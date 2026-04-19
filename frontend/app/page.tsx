// app/page.tsx — Temporary root page (redirects to dashboard)
import { redirect } from "next/navigation";

export default function RootPage() {
  redirect("/dashboard");
}
