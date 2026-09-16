export default function NotFound() {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center bg-background gap-4">
      <p className="font-heading text-5xl font-bold text-foreground">404</p>
      <p className="text-sm text-muted-foreground">This page doesn't exist.</p>
      <a href="/app" className="text-sm text-blue-600 hover:underline dark:text-blue-400">Go to dashboard</a>
    </div>
  );
}
