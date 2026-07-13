import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const siteUrl = 'http://localhost:5173';
const appHref = new URL('/', siteUrl).href;

const config: Config = {
  title: 'SceneGEMS',
  tagline:
    'User interface documentation for SceneGEMS,the maritime ASV scenario generation and simulation console',
  favicon: 'img/favicon.svg',

  future: {
    v4: true,
  },

  url: siteUrl,
  baseUrl: '/docs/',

  onBrokenLinks: 'throw',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.ts',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    colorMode: {
      defaultMode: 'dark',
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'SceneGEMS Docs',
      logo: {
        alt: 'SceneGEMS',
        src: 'img/favicon.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'uiSidebar',
          position: 'left',
          label: 'User interface',
        },
        {
          type: 'html',
          position: 'right',
          value:
            '<a class="navbar__item navbar__link" href="/docs/scenegems-ui-documentation.pdf" download>Download PDF</a>',
        },
        {
          href: appHref,
          label: 'Open app',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Documentation',
          items: [
            {
              label: 'Overview',
              to: '/',
            },
            {
              label: 'Typical workflow',
              to: '/workflow',
            },
          ],
        },
        {
          title: 'Application',
          items: [
            {
              label: 'Open SceneGEMS',
              href: appHref,
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} SceneGEMS. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
