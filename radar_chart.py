import matplotlib.pyplot as plt
import numpy as np

categories = [
    'Multi-Agent\nOrchestration',
    'Memory &\nKnowledge',
    'Tool\nEcosystem',
    'Self-Correction\n& Reflection',
    'Sandboxing\n& Isolation',
    'Browser &\nVision',
    'Search\nIntegration',
    'Observability\n& Monitoring',
    'Human-in-\nthe-Loop',
    'Cost &\nBudget Mgmt',
]

# Scores out of 10
agent_nimi   = [6, 6, 7, 7, 3, 1, 1, 4, 5, 3]
pentagi      = [9, 9, 9, 8, 10, 7, 10, 10, 6, 5]
magentic_one = [10, 7, 7, 9, 8, 9, 5, 6, 7, 4]
mapta        = [8, 5, 7, 7, 9, 3, 4, 4, 3, 9]

N = len(categories)
angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
angles += angles[:1]

def close_data(data):
    return data + data[:1]

fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(polar=True))
fig.patch.set_facecolor('#0d1117')
ax.set_facecolor('#0d1117')

ax.plot(angles, close_data(agent_nimi), 'o-', linewidth=2.5, label='Agent-Nimi', color='#58a6ff', markersize=7)
ax.fill(angles, close_data(agent_nimi), alpha=0.15, color='#58a6ff')

ax.plot(angles, close_data(pentagi), 'o-', linewidth=2.5, label='PentAGI', color='#f97583', markersize=7)
ax.fill(angles, close_data(pentagi), alpha=0.10, color='#f97583')

ax.plot(angles, close_data(magentic_one), 'o-', linewidth=2.5, label='Magentic-One', color='#56d364', markersize=7)
ax.fill(angles, close_data(magentic_one), alpha=0.10, color='#56d364')

ax.plot(angles, close_data(mapta), 'o-', linewidth=2.5, label='MAPTA', color='#d2a8ff', markersize=7)
ax.fill(angles, close_data(mapta), alpha=0.10, color='#d2a8ff')

ax.set_xticks(angles[:-1])
ax.set_xticklabels(categories, fontsize=10, color='#c9d1d9', fontweight='bold')
ax.set_yticks([2, 4, 6, 8, 10])
ax.set_yticklabels(['2', '4', '6', '8', '10'], fontsize=8, color='#8b949e')
ax.set_ylim(0, 10)
ax.spines['polar'].set_color('#30363d')
ax.grid(color='#30363d', linewidth=0.5)
ax.tick_params(axis='x', pad=18)

legend = ax.legend(loc='upper right', bbox_to_anchor=(1.35, 1.1), fontsize=11,
                   facecolor='#161b22', edgecolor='#30363d', labelcolor='#c9d1d9')

plt.title('Agent-Nimi vs. Leading AI Agent Projects\nFeature Comparison (2026)',
          fontsize=16, fontweight='bold', color='#c9d1d9', pad=30)

plt.tight_layout()
plt.savefig('/home/ubuntu/radar_comparison.png', dpi=150, bbox_inches='tight',
            facecolor='#0d1117', edgecolor='none')
print("Saved radar_comparison.png")
