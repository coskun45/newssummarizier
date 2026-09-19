import { Squares2X2Icon } from '@heroicons/react/24/outline';
import featuresData from '../../data/features.json';
import { useAppInfo } from '../../hooks/useApi';
import type { FeaturesData } from '../../types';
import './Features.css';

const versionNumber = (version: string) => Number(version.slice(1));

function Features() {
  const { data: appInfo } = useAppInfo();
  // Newest version first.
  const versions = [...(featuresData as FeaturesData).versions].sort(
    (a, b) => versionNumber(b.version) - versionNumber(a.version),
  );

  return (
    <div className="settings-category">
      <h2 className="settings-content-title"><Squares2X2Icon className="section-icon" /> Features</h2>
      <p className="features-intro">Uygulamada şu anda bulunan özellikler, sürümlere göre.</p>
      {appInfo?.version && (
        <p className="features-current-version">Güncel sürüm: <strong>v{appInfo.version}</strong></p>
      )}
      {versions.map(({ version, title, features }) => (
        <section key={version} className="features-group">
          <h3 className="features-group-title">{version} · {title}</h3>
          <ul className="features-list">
            {features.map((feature) => (
              <li key={feature.id} className="features-card">
                <h4 className="features-card-title">{feature.title}</h4>
                <p className="features-card-description">{feature.description}</p>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

export default Features;
