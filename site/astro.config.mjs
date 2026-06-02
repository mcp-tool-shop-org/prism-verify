// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import tailwindcss from '@tailwindcss/vite';

// https://astro.build/config
export default defineConfig({
  site: 'https://mcp-tool-shop-org.github.io',
  base: '/prism-verify',
  integrations: [
    starlight({
      title: 'prism-verify',
      description: 'Runtime LLM verifier — family-different, reasoning-stripped, multi-lens, signed Ed25519 receipts.',
      logo: {
        src: './src/assets/logo.png',
        alt: 'prism-verify',
        href: '/prism-verify/', // link the handbook header back to the landing page
        replacesTitle: false,
      },
      disable404Route: true,
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/mcp-tool-shop-org/prism-verify' },
      ],
      sidebar: [
        {
          label: 'Handbook',
          autogenerate: { directory: 'handbook' },
        },
      ],
      customCss: ['./src/styles/starlight-custom.css'],
    }),
  ],
  vite: {
    plugins: [tailwindcss()],
  },
});
