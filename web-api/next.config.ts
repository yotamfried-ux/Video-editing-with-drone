import type { NextConfig } from 'next';

const securityHeaders = [
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
];

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: '/:path*',
        headers: securityHeaders,
      },
    ];
  },
  async redirects() {
    return [
      { source: '/operator/review', destination: '/review', permanent: false },
      { source: '/operator', destination: '/pipeline', permanent: false },
    ];
  },
  async rewrites() {
    return {
      fallback: [
        {
          source: '/:path((?!api/|_next/|_expo/|assets/|checkout/success$|checkout/cancel$|legal/).*)',
          destination: '/_spa.html',
        },
      ],
    };
  },
};

export default nextConfig;

