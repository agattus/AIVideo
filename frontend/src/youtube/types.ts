export type YtVideo = {
  id: string;
  title: string;
  channel: string;
  channelHandle: string;
  channelAvatar: string;
  views: string;
  uploadedAt: string;
  duration: string;
  thumbnail: string;
  videoUrl?: string | null;
  description: string;
  category: string;
  likes: string;
  subscribers: string;
  isShort?: boolean;
  isLive?: boolean;
  verified?: boolean;
  source: "demo" | "library" | "upload";
  jobId?: string;
  canEdit?: boolean;
  heat?: string;
};

export type YtComment = {
  id: string;
  author: string;
  avatar: string;
  text: string;
  likes: string;
  postedAt: string;
};
