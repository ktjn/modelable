import type { ReactNode } from 'react';
import { Group, Panel, Separator } from 'react-resizable-panels';

export interface ResizableLayoutProps {
  explorer: ReactNode;
  editor: ReactNode;
  visualization: ReactNode;
  bottom: ReactNode;
  mobileView: 'source' | 'graph' | 'analysis';
}

export function ResizableLayout({
  explorer,
  editor,
  visualization,
  bottom,
  mobileView,
}: ResizableLayoutProps) {
  return (
    <div className="resizable-layout" data-mobile-view={mobileView}>
      <Group orientation="vertical" className="resizable-layout__outer">
        <Panel defaultSize="70%" minSize="30%" className="resizable-layout__main">
          <Group orientation="horizontal" className="resizable-layout__columns">
            <Panel
              defaultSize="20%"
              minSize="10%"
              maxSize="35%"
              collapsible
              collapsedSize="0%"
              className="resizable-layout__explorer"
              tabIndex={0}
            >
              {explorer}
            </Panel>
            <Separator className="resize-handle resize-handle--horizontal" />
            <Panel defaultSize="45%" minSize="20%" className="resizable-layout__editor">
              {editor}
            </Panel>
            <Separator className="resize-handle resize-handle--horizontal" />
            <Panel defaultSize="35%" minSize="15%" collapsible collapsedSize="0%" className="resizable-layout__visualization">
              {visualization}
            </Panel>
          </Group>
        </Panel>
        <Separator className="resize-handle resize-handle--vertical" />
        <Panel defaultSize="30%" minSize="10%" collapsible collapsedSize="0%" className="resizable-layout__bottom">
          {bottom}
        </Panel>
      </Group>
    </div>
  );
}
