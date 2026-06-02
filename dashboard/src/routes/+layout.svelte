<script>
  import '../app.css';

  const links = [
    { href: './', label: 'Overview' },
    { href: './routes', label: 'Routes' },
    { href: './fleet', label: 'Fleet' },
    { href: './events', label: 'Events' },
    { href: './telemetry', label: 'Telemetry' },
    { href: './routes_map', label: 'Map' },
  ];
</script>

<div class="app">
  <nav class="topnav">
    <div class="nav-brand">
      <div class="logo">H</div>
      <div class="brand-text">
        <span class="brand-name">HERMES</span>
        <span class="brand-sub">Operations Intelligence</span>
      </div>
    </div>
    <div class="nav-links">
      {#each links as link}
        <a href={link.href} class="nav-link">{link.label}</a>
      {/each}
    </div>
    <div class="nav-status">
      <span class="dot"></span>
      <span>Latest run &middot; RUN-BD2601B0</span>
    </div>
  </nav>

  <main class="content">
    <slot />
  </main>
</div>

<style>
  .app {
    min-height: 100vh;
    background: var(--color-background-primary, #fff);
  }

  .topnav {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 24px;
    height: 52px;
    border-bottom: 1px solid var(--color-border-tertiary, #e5e7eb);
    background: var(--color-background-primary, #fff);
    position: sticky;
    top: 0;
    z-index: 50;
  }

  .nav-brand {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .logo {
    width: 28px;
    height: 28px;
    background: #1D9E75;
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    font-weight: 600;
    font-size: 14px;
    letter-spacing: -0.02em;
  }

  .brand-text {
    display: flex;
    flex-direction: column;
    line-height: 1.2;
  }

  .brand-name {
    font-size: 14px;
    font-weight: 500;
    color: var(--color-text-primary, #111827);
    letter-spacing: -0.01em;
  }

  .brand-sub {
    font-size: 11px;
    color: var(--color-text-secondary, #6b7280);
    margin-top: 1px;
  }

  .nav-links {
    display: flex;
    gap: 2px;
  }

  .nav-link {
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 12.5px;
    font-weight: 400;
    color: var(--color-text-secondary, #6b7280);
    text-decoration: none;
    transition: all 0.15s ease;
    border: 1px solid transparent;
  }

  .nav-link:hover {
    color: var(--color-text-primary, #111827);
    background: var(--color-background-secondary, #f9fafb);
  }

  .nav-status {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: var(--color-text-secondary, #6b7280);
  }

  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #1D9E75;
  }

  .content {
    padding: 20px 24px 40px;
    max-width: 1200px;
    margin: 0 auto;
  }
</style>
