import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  uiSidebar: [
    'intro',
    'layout',
    'navigation',
    {
      type: 'category',
      label: 'Main views',
      collapsed: false,
      items: [
        'domain-configuration',
        'scene-generation',
        'simulation',
        'waraps',
      ],
    },
    {
      type: 'category',
      label: 'Visualization & controls',
      collapsed: false,
      items: [
        'scene-canvas',
        'control-panel',
        'monitoring',
        'metrics',
        'recording',
      ],
    },
    {
      type: 'category',
      label: 'Reference',
      collapsed: false,
      items: [
        'resizing',
        'persistence',
        'status',
        'workflow',
      ],
    },
  ],
};

export default sidebars;
