import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  uiSidebar: [
    'intro',
    'layout',
    'navigation',
    {
      type: 'category',
      label: 'Workbench',
      collapsed: false,
      items: [
        'workbench-pages',
        'design-space-exploration',
        'scene-generation',
        'trajectory-generation',
        'simulation',
        'connections',
      ],
    },
    {
      type: 'category',
      label: 'Cluster sections',
      collapsed: false,
      items: [
        'cluster',
        'domain-configuration',
        'capabilities',
        'campaigns',
        'campaign-wizard',
        'campaign-history',
        'results',
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
