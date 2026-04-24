import { useState, useEffect } from 'react';
import { getAgents, AgentCard } from '../api/marketplace';

const CATEGORIES = ['All', 'HR', 'IT', 'Sales', 'Security', 'Finance'];

export default function MarketplacePage() {
  const [agents, setAgents] = useState<AgentCard[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState('All');

  useEffect(() => {
    const fetchAgents = async () => {
      setIsLoading(true);
      try {
        const data = await getAgents(searchQuery, activeCategory);
        setAgents(data);
      } catch (error) {
        console.error('Failed to fetch agents:', error);
      } finally {
        setIsLoading(false);
      }
    };

    // 간단한 디바운싱 (Debouncing) 적용
    const timer = setTimeout(() => {
      fetchAgents();
    }, 300);

    return () => clearTimeout(timer);
  }, [searchQuery, activeCategory]);

  return (
    <div className="animate-fade-in font-apple">
      {/* Header Section */}
      <div className="mb-8">
        <h1 className="text-[32px] font-semibold text-white tracking-[0.196px] leading-[1.14] mb-2">마켓플레이스</h1>
        <p className="text-[17px] text-white/50 tracking-[-0.224px]">조직 내에 등록된 에이전트를 검색하고 구독하세요.</p>
      </div>

      {/* Search Bar */}
      <div className="relative mb-6">
        <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
          <svg className="h-5 w-5 text-white/40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>
        <input
          type="text"
          className="w-full bg-apple-surface1 border border-white/10 rounded-[12px] py-[12px] pl-[40px] pr-[16px] text-white text-[17px] focus:outline-none focus:ring-2 focus:ring-apple-blue transition-all"
          placeholder="이름, 설명 또는 목적으로 검색..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      {/* Categories Horizontal Scroll */}
      <div className="flex gap-2 mb-8 overflow-x-auto pb-2 scrollbar-hide">
        {CATEGORIES.map((category) => (
          <button
            key={category}
            onClick={() => setActiveCategory(category)}
            className={`flex-shrink-0 px-[16px] py-[8px] rounded-[980px] text-[14px] font-medium tracking-[-0.12px] transition-all duration-200 ${
              activeCategory === category
                ? 'bg-apple-blue text-white'
                : 'bg-apple-surface1 text-white/60 hover:bg-white/10 hover:text-white'
            }`}
          >
            {category}
          </button>
        ))}
      </div>

      {/* Agents Grid */}
      {isLoading ? (
        <div className="flex justify-center items-center py-20">
          <div className="w-8 h-8 border-2 border-white/20 border-t-apple-blue rounded-full animate-spin" />
        </div>
      ) : agents.length === 0 ? (
        <div className="text-center py-20 bg-apple-surface1 rounded-[12px]">
          <svg className="mx-auto h-12 w-12 text-white/20 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <h3 className="text-[17px] font-medium text-white mb-1">결과가 없습니다</h3>
          <p className="text-[14px] text-white/50">다른 검색어 카테고리를 시도해 보세요.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {agents.map((agent) => (
            <div key={agent.agent_id} className="bg-apple-surface1 rounded-[16px] p-6 shadow-[0_5px_30px_rgba(0,0,0,0.22)] flex flex-col h-full border border-white/5 transition-transform duration-200 hover:scale-[1.02]">
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-[12px] bg-apple-surface2 flex items-center justify-center">
                    <span className="text-[21px] font-semibold text-white">{agent.name.charAt(0)}</span>
                  </div>
                  <div>
                    <h3 className="text-[17px] font-semibold text-white tracking-[-0.224px] leading-tight line-clamp-1">{agent.name}</h3>
                    <p className="text-[12px] text-white/50 mt-1">v{agent.version}</p>
                  </div>
                </div>
                {agent.metadata_?.category && (
                  <span className="px-2 py-1 bg-apple-surface2 rounded-[6px] text-[11px] font-medium text-apple-blue border border-apple-blue/20">
                    {agent.metadata_.category}
                  </span>
                )}
              </div>
              
              <div className="flex-grow mb-6">
                <p className="text-[14px] text-white/70 tracking-[-0.12px] leading-relaxed line-clamp-3">
                  {agent.description || agent.purpose || '설명이 없습니다.'}
                </p>
              </div>
              
              <div className="mt-auto pt-4 border-t border-white/5 flex justify-between items-center">
                <div className="flex -space-x-2">
                  {/* Tool Badges - Dummy visual representation */}
                  {agent.tools.slice(0, 3).map((tool, i) => (
                    <div key={i} className="w-6 h-6 rounded-full bg-apple-surface2 border border-apple-surface1 flex items-center justify-center" title={tool}>
                      <span className="text-[8px] text-white/50">{tool.charAt(0).toUpperCase()}</span>
                    </div>
                  ))}
                  {agent.tools.length > 3 && (
                    <div className="w-6 h-6 rounded-full bg-apple-surface2 border border-apple-surface1 flex items-center justify-center">
                      <span className="text-[8px] text-white/50">+{agent.tools.length - 3}</span>
                    </div>
                  )}
                </div>
                <button className="text-[14px] font-medium text-apple-blue hover:text-white transition-colors bg-apple-blue/10 px-3 py-1.5 rounded-[8px]">
                  상세보기
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
