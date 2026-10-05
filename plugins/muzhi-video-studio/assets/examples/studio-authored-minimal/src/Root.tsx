import React from 'react';
import {Composition} from 'remotion';
import {AuthoredStudy} from './Scene';

export const Root: React.FC = () => <Composition id="Studio-Authored-Minimal" component={AuthoredStudy}
  durationInFrames={120} fps={30} width={720} height={1280}/>;
