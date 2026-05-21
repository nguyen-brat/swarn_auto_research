import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  output: 'static',
  integrations: [
    starlight({
      title: 'Swarn Research Handbook',
      customCss: ['./src/styles/custom.css'],
      sidebar: [
        { label: 'Home', slug: 'index' },
        { label: 'Runs', autogenerate: { directory: 'runs' } },
      ],
    }),
  ],
});
