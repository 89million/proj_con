import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SeasonState(str, enum.Enum):
    submit = "submit"
    ranking = "ranking"
    bracket = "bracket"
    complete = "complete"


class IdeaStatus(str, enum.Enum):
    proposed = "proposed"
    in_progress = "in_progress"
    done = "done"
    wont_do = "wont_do"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    google_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def visible_name(self) -> str:
        return self.display_name or self.name

    books: Mapped[list["Book"]] = relationship("Book", back_populates="submitter")
    borda_votes: Mapped[list["BordaVote"]] = relationship("BordaVote", back_populates="user")
    bracket_votes: Mapped[list["BracketVote"]] = relationship("BracketVote", back_populates="user")
    read_books_added: Mapped[list["ReadBook"]] = relationship(
        "ReadBook", back_populates="added_by_user"
    )
    season_participations: Mapped[list["SeasonParticipant"]] = relationship(
        "SeasonParticipant", back_populates="user"
    )


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[SeasonState] = mapped_column(Enum(SeasonState), default=SeasonState.submit)
    page_limit: Mapped[int] = mapped_column(Integer, default=400)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    books: Mapped[list["Book"]] = relationship("Book", back_populates="season")
    seeds: Mapped[list["Seed"]] = relationship("Seed", back_populates="season")
    matchups: Mapped[list["BracketMatchup"]] = relationship(
        "BracketMatchup", back_populates="season"
    )
    participants: Mapped[list["SeasonParticipant"]] = relationship(
        "SeasonParticipant", back_populates="season"
    )


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        UniqueConstraint("submitter_id", "season_id", name="uq_one_book_per_member_per_season"),
        UniqueConstraint("title", "author", "season_id", name="uq_no_duplicate_titles_per_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[str] = mapped_column(String, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    submitter: Mapped["User"] = relationship("User", back_populates="books")
    season: Mapped["Season"] = relationship("Season", back_populates="books")
    borda_votes: Mapped[list["BordaVote"]] = relationship("BordaVote", back_populates="book")
    seed: Mapped["Seed | None"] = relationship("Seed", back_populates="book", uselist=False)


class ReadBook(Base):
    """Books the club has already read (admin-managed). Won books can never be re-submitted."""

    __tablename__ = "read_books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[str] = mapped_column(String, nullable=False)
    won: Mapped[bool] = mapped_column(Boolean, default=False)
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    added_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    added_by_user: Mapped["User"] = relationship("User", back_populates="read_books_added")
    reviews: Mapped[list["BookReview"]] = relationship(
        "BookReview", back_populates="read_book", cascade="all, delete-orphan"
    )


class BordaVote(Base):
    """A single book's rank within a user's full ranking submission."""

    __tablename__ = "borda_votes"
    __table_args__ = (
        UniqueConstraint("user_id", "season_id", "book_id", name="uq_one_rank_per_book_per_voter"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 = top choice
    submitted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="borda_votes")
    book: Mapped["Book"] = relationship("Book", back_populates="borda_votes")


class Seed(Base):
    """Tournament seed computed from Borda count after all rankings are in."""

    __tablename__ = "seeds"
    __table_args__ = (
        UniqueConstraint("season_id", "book_id", name="uq_one_seed_per_book"),
        UniqueConstraint("season_id", "seed", name="uq_one_book_per_seed"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 = best

    season: Mapped["Season"] = relationship("Season", back_populates="seeds")
    book: Mapped["Book"] = relationship("Book", back_populates="seed")


class BracketMatchup(Base):
    """A single matchup in the bracket. round 1 = earliest round, highest round = Final."""

    __tablename__ = "bracket_matchups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # slot within round
    book_a_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    book_b_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("books.id"), nullable=True)

    season: Mapped["Season"] = relationship("Season", back_populates="matchups")
    book_a: Mapped["Book"] = relationship("Book", foreign_keys=[book_a_id])
    book_b: Mapped["Book"] = relationship("Book", foreign_keys=[book_b_id])
    winner: Mapped["Book | None"] = relationship("Book", foreign_keys=[winner_id])
    votes: Mapped[list["BracketVote"]] = relationship("BracketVote", back_populates="matchup")


class BracketVote(Base):
    """A user's vote for one book in a specific bracket matchup."""

    __tablename__ = "bracket_votes"
    __table_args__ = (
        UniqueConstraint("user_id", "matchup_id", name="uq_one_vote_per_matchup_per_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    matchup_id: Mapped[int] = mapped_column(ForeignKey("bracket_matchups.id"), nullable=False)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    voted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="bracket_votes")
    matchup: Mapped["BracketMatchup"] = relationship("BracketMatchup", back_populates="votes")
    book: Mapped["Book"] = relationship("Book")


class SeasonParticipant(Base):
    """Explicit per-season participation record. Created when a season is started;
    users can opt out before submitting, and admins can add/remove at any time."""

    __tablename__ = "season_participants"
    __table_args__ = (
        UniqueConstraint("season_id", "user_id", name="uq_one_participant_per_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    season: Mapped["Season"] = relationship("Season", back_populates="participants")
    user: Mapped["User"] = relationship("User", back_populates="season_participations")


class FeatureIdea(Base):
    """A user-submitted feature idea for the app."""

    __tablename__ = "feature_ideas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    complexity: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[IdeaStatus] = mapped_column(
        Enum(IdeaStatus), default=IdeaStatus.proposed, server_default="proposed"
    )
    admin_note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    author: Mapped["User"] = relationship("User")
    upvotes: Mapped[list["IdeaUpvote"]] = relationship(
        "IdeaUpvote", back_populates="idea", cascade="all, delete-orphan"
    )


class IdeaUpvote(Base):
    """Anonymous upvote on a feature idea (one per user per idea)."""

    __tablename__ = "idea_upvotes"
    __table_args__ = (
        UniqueConstraint("idea_id", "user_id", name="uq_one_upvote_per_user_per_idea"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idea_id: Mapped[int] = mapped_column(ForeignKey("feature_ideas.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    idea: Mapped["FeatureIdea"] = relationship("FeatureIdea", back_populates="upvotes")


class BookReview(Base):
    """A user's star rating and optional text review for a read book."""

    __tablename__ = "book_reviews"
    __table_args__ = (
        UniqueConstraint("read_book_id", "user_id", name="uq_one_review_per_user_per_book"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    read_book_id: Mapped[int] = mapped_column(ForeignKey("read_books.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1–5 stars
    review_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    read_book: Mapped["ReadBook"] = relationship("ReadBook", back_populates="reviews")
    user: Mapped["User"] = relationship("User")
