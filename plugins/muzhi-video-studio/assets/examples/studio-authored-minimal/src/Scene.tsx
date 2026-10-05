import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';

export const AuthoredStudy: React.FC = () => {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{background: '#F7F2E7', color: '#173447', fontFamily: 'Microsoft YaHei',
    display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 50}}>
    <div style={{fontSize: 35}}>先看条件，再决定是否继续。</div>
    {frame >= 60 && <div style={{fontSize: 40, color: '#B65D3D'}}>条件未核 · 待定</div>}
  </AbsoluteFill>;
};
