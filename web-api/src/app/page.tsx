export default function HomePage() {
  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        padding: '24px',
        fontFamily: 'system-ui, sans-serif',
        textAlign: 'center',
      }}
    >
      <section>
        <h1>SportReel</h1>
        <h2>Email confirmed</h2>
        <p>Your email address has been verified successfully.</p>
        <p>You can return to the SportReel app and sign in.</p>
        <p style={{ marginTop: 16 }}>
          <a href="/discover" style={{ color: '#38BDF8', fontWeight: 600 }}>
            Continue to SportReel Web
          </a>
        </p>
      </section>
    </main>
  );
}
